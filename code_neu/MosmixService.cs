using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net.Http;

public class MosmixService
{
    private readonly string _run;

    public MosmixService(string run)
    {
        _run = run;
    }

    public MosmixData LoadMosmixData(DateTime today)
    {
        var stations = ParseFromDwdLatest();
        var stationen = MosmixParser.FilterGermany(stations).ToList();
        return BuildMosmixData(stationen, today);
    }

    public MosmixData LoadMosmixDataLatest(DateTime today)
    {
        // Nur im 00z-Lauf: Tag 1 aus echter 00z-Datei
        if (_run == "00z" || true)
        {
            var stations00 = ParseFromDwd00z();
            var stationen00 = MosmixParser.FilterGermany(stations00).ToList();
            var data00 = BuildMosmixData(stationen00, today);

            double firstDay00 = data00.DailyTempMean[today];

            // Rest wie bisher aus LATEST
            var stationsLatest = ParseFromDwdLatest();
            var stationenLatest = MosmixParser.FilterGermany(stationsLatest).ToList();
            var dataLatest = BuildMosmixData(stationenLatest, today);

            // Nur Tag 1 ersetzen
            dataLatest.DailyTempMean[today] = firstDay00;

            return dataLatest;
        }

        // Alle anderen Läufe unverändert
        var stations = ParseFromDwdLatest();
        var stationen = MosmixParser.FilterGermany(stations).ToList();
        return BuildMosmixData(stationen, today);
    }

    private List<MosmixParser.StationData> ParseFromDwdLatest()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        string fileName = "MOSMIX_S_LATEST_240.kmz";
        string url = $"https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_S/all_stations/kml/{fileName}";
        string kmzPath = Path.Combine(tempDir, fileName);

        using (var http = new HttpClient())
        {
            var bytes = http.GetByteArrayAsync(url).Result;
            File.WriteAllBytes(kmzPath, bytes);
        }

        try
        {
            var parser = new MosmixParser();
            return parser.ParseKmz(kmzPath);
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { }
        }
    }

    private List<MosmixParser.StationData> ParseFromDwd00z()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix00_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        // Beispiel heute (12.07.2026):
        // DateTime.UtcNow.Date = 2026-07-12
        // -> MOSMIX_S_2026071200_240.kmz
        var runDate = DateTime.UtcNow.Date;
        string fileName = $"MOSMIX_S_{runDate:yyyyMMdd}00_240.kmz";

        string url = $"https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_S/all_stations/kml/{fileName}";
        string kmzPath = Path.Combine(tempDir, fileName);

        using (var http = new HttpClient())
        {
            var bytes = http.GetByteArrayAsync(url).Result;
            File.WriteAllBytes(kmzPath, bytes);
        }

        try
        {
            var parser = new MosmixParser();
            return parser.ParseKmz(kmzPath);
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { }
        }
    }



    private MosmixData BuildMosmixData(List<MosmixParser.StationData> stationen, DateTime today)
    {
        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;

        var mosmix = new MosmixParser();

        string[] wantedOrder =
        {
            "SCHLESWIG",
            "KIEL-H.",
            "ARKONA",
            "HAMBURG-NEUENG.",
            "POTSDAM",
            "BREMEN",
            "BEVERN",
            "BIELEFELD-DEPPENDORF",
            "DIEPHOLZ",
            "WERL",
            "GOETTINGEN",
            "LEINEFELDE",
            "DRESDEN-HOSTERWITZ",
            "GOERLITZ",
            "BONN-ROLEBER",
            "FRANKFURT/M",
            "SCHMELZ-HUETTERSDORF",
            "BERUS",
            "NUERNBERG",
            "STUTTGART-SCHN.",
            "FREIBURG",
            "MUENCHEN STADT"
        };

        var sunshine16 = new Dictionary<string, (double Total, Dictionary<int, double> Days)>();
        foreach (var w in wantedOrder)
            sunshine16[w] = (0.0, new Dictionary<int, double>());

        foreach (var st in stationen)
        {
            string name = st.Name?.Trim();
            if (!sunshine16.ContainsKey(name))
                continue;

            var perDay = new Dictionary<int, double>();

            foreach (var kv in st.SunshineSecondsPerHour)
            {
                var d = kv.Key;
                if (d.Year != year || d.Month != month || d.Day < todayDay)
                    continue;

                int day = d.Day;
                if (!perDay.ContainsKey(day))
                    perDay[day] = 0;

                perDay[day] += kv.Value / 3600.0;
            }

            double total = perDay.Values.Sum();
            sunshine16[name] = (total, perDay);
        }

        var dailySunMean = mosmix.ComputeGermanyDailySunHours(stationen);
        var dailyRainMean = mosmix.ComputeGermanyDailyRainMm(stationen);
        var dailyTempMean = mosmix.ComputeGermanyDailyTempC(stationen);
        var top10 = mosmix.ComputeTop10DailyMaxTempForTodayAndTomorrow(stationen);

        DateTime? invalidDateOpt = dailySunMean.Count > 0
            ? dailySunMean.Keys.Max()
            : (DateTime?)null;

        if (invalidDateOpt.HasValue)
        {
            var invalidDate = invalidDateOpt.Value;

            dailySunMean.Remove(invalidDate);
            dailyRainMean.Remove(invalidDate);
            dailyTempMean.Remove(invalidDate);

            foreach (var st in stationen)
                st.DailyMaxTemp.Remove(invalidDate);

            int invalidDay = invalidDate.Day;

            foreach (var key in sunshine16.Keys.ToList())
            {
                var entry = sunshine16[key];
                if (entry.Days.ContainsKey(invalidDay))
                {
                    entry.Days.Remove(invalidDay);
                    double newTotal = entry.Days.Values.Sum();
                    sunshine16[key] = (newTotal, entry.Days);
                }
            }
        }

        var climate = DataLoader.LoadClimateData();
        var observed = DataLoader.LoadObservedData();

        var climateSun = climate.Sun;
        var climateRain = climate.Rain;
        var climateTemp = climate.Temp;

        var observedSun = observed.Sun;
        var observedRain = observed.Rain;
        var observedTemp = observed.Temp;

        return new MosmixData
        {
            AllStations = stationen,
            DailySunMean = dailySunMean,
            DailyRainMean = dailyRainMean,
            DailyTempMean = dailyTempMean,
            Top10 = top10,
            ObservedSun = observedSun,
            ObservedRain = observedRain,
            ObservedTemp = observedTemp,
            ClimateSun = climateSun,
            ClimateRain = climateRain,
            ClimateTemp = climateTemp,
            Sunshine16Stations = sunshine16
        };
    }

    public void SaveMosmixForecastsToDatabase(MosmixData data, DateTime today, string modelName)
    {
        var repo = new ForecastRepository();

        foreach (var kv in data.DailyTempMean)
        {
            DateTime date = kv.Key;
            decimal? tmk = (decimal?)kv.Value;

            decimal? sdk = null;
            if (data.DailySunMean.TryGetValue(date, out var sun))
                sdk = (decimal?)sun;

            decimal? rsk = null;
            if (data.DailyRainMean.TryGetValue(date, out var rain))
                rsk = (decimal?)rain;

            int vorhersageTag = (date - today.Date).Days;

            repo.InsertForecast(
                date,
                modelName,
                vorhersageTag,
                tmk,
                sdk,
                rsk
            );
        }
    }

}

public class MosmixData
{
    public Dictionary<string, (double Total, Dictionary<int, double> Days)> Sunshine16Stations { get; set; }

    public List<MosmixParser.StationData> AllStations { get; set; }

    public Dictionary<DateTime, double> DailySunMean { get; set; }
    public Dictionary<DateTime, double> DailyRainMean { get; set; }
    public Dictionary<DateTime, double> DailyTempMean { get; set; }

    public Dictionary<DateTime, List<(string Station, double Tmax)>> Top10 { get; set; }

    public double[] ObservedSun { get; set; }
    public double[] ObservedRain { get; set; }
    public double[] ObservedTemp { get; set; }

    public double[] ClimateSun { get; set; }
    public double[] ClimateRain { get; set; }
    public double[] ClimateTemp { get; set; }
}
