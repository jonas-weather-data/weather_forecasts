using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net.Http;
using System.Xml.Linq;

public class MosmixParser
{
    private const string MosmixLatestUrl =
        "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_S/all_stations/kml/MOSMIX_S_LATEST_240.kmz";

    public class StationData
    {
        public string StationId { get; set; }
        public double Latitude { get; set; }
        public double Longitude { get; set; }

        public string Name { get; set; }

        public Dictionary<DateTime, double> SunshineSecondsPerHour { get; } = new();
        public Dictionary<DateTime, double> RainMmPerHour { get; } = new();
        public Dictionary<DateTime, double> TempCPerHour { get; } = new();
        public Dictionary<DateTime, double> DailyMaxTemp { get; } = new();
        public string Code { get; set; }
        public double Height { get; set; }
    }

    // Nur noch LATEST, kein 00z-Sonderpfad mehr
    public List<StationData> ParseFromDwd()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        string fileName = "MOSMIX_S_LATEST_240.kmz";
        string kmzPath = Path.Combine(tempDir, fileName);

        using (var http = new HttpClient())
        {
            var bytes = http.GetByteArrayAsync(MosmixLatestUrl).Result;
            File.WriteAllBytes(kmzPath, bytes);
        }

        try
        {
            var allStations = ParseKmz(kmzPath);
            return FilterGermany(allStations).ToList();
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { }
        }
    }

    public List<StationData> ParseKmz(string kmzPath)
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        try
        {
            ZipFile.ExtractToDirectory(kmzPath, tempDir);
            string kmlPath = Directory.GetFiles(tempDir, "*.kml", SearchOption.AllDirectories).First();

            XDocument doc = XDocument.Load(kmlPath);

            XNamespace kml = "http://www.opengis.net/kml/2.2";
            XNamespace dwd = "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd";

            var timeSteps = doc.Descendants(dwd + "TimeStep")
                               .Select(x => DateTime.Parse(x.Value, null, DateTimeStyles.AdjustToUniversal))
                               .ToList();

            var stations = new List<StationData>();

            foreach (var placemark in doc.Descendants(kml + "Placemark"))
            {
                var id = placemark.Element(kml + "name")?.Value?.Trim();
                var desc = placemark.Element(kml + "description")?.Value?.Trim();
                if (string.IsNullOrEmpty(id))
                    continue;

                var coordText = placemark.Descendants(kml + "coordinates").First().Value.Trim();
                var parts = coordText.Split(',');
                double lon = double.Parse(parts[0], CultureInfo.InvariantCulture);
                double lat = double.Parse(parts[1], CultureInfo.InvariantCulture);
                double height = 0;
                if (parts.Length > 2)
                    height = double.Parse(parts[2], CultureInfo.InvariantCulture);

                var station = new StationData
                {
                    StationId = id,
                    Code = id,
                    Name = string.IsNullOrWhiteSpace(desc) ? id : desc,
                    Latitude = lat,
                    Longitude = lon,
                    Height = height
                };

                var sunD1Node = placemark.Descendants(dwd + "Forecast")
                                         .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "SunD1");

                if (sunD1Node != null)
                {
                    var values = sunD1Node.Element(dwd + "value")?.Value?
                        .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                        .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d) ? d : 0)
                        .ToList();

                    if (values != null && values.Count == timeSteps.Count)
                        for (int i = 0; i < timeSteps.Count; i++)
                            station.SunshineSecondsPerHour[timeSteps[i]] = values[i];
                }

                var rr1cNode = placemark.Descendants(dwd + "Forecast")
                                        .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "RR1c");

                if (rr1cNode != null)
                {
                    var values = rr1cNode.Element(dwd + "value")?.Value?
                        .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                        .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d) ? d : 0)
                        .ToList();

                    if (values != null && values.Count == timeSteps.Count)
                        for (int i = 0; i < timeSteps.Count; i++)
                            station.RainMmPerHour[timeSteps[i]] = values[i];
                }

                var tttNode = placemark.Descendants(dwd + "Forecast")
                                       .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "TTT");

                if (tttNode != null)
                {
                    var values = tttNode.Element(dwd + "value")?.Value?
                        .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                        .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d)
                                     ? d - 273.15
                                     : 0)
                        .ToList();

                    if (values != null && values.Count == timeSteps.Count)
                        for (int i = 0; i < timeSteps.Count; i++)
                            station.TempCPerHour[timeSteps[i]] = values[i];
                }

                var txNode = placemark.Descendants(dwd + "Forecast")
                                      .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "TX");

                if (txNode != null)
                {
                    var values = txNode.Element(dwd + "value")?.Value?
                        .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                        .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d)
                                     ? d - 273.15
                                     : 0)
                        .ToList();

                    if (values != null && values.Count == timeSteps.Count)
                    {
                        for (int i = 0; i < timeSteps.Count; i++)
                        {
                            var day = timeSteps[i].Date;
                            var val = values[i];

                            if (!station.DailyMaxTemp.ContainsKey(day) || val > station.DailyMaxTemp[day])
                                station.DailyMaxTemp[day] = val;
                        }
                    }
                }

                stations.Add(station);
            }

            return stations;
        }
        finally
        {
            try { Directory.Delete(tempDir, true); } catch { }
        }
    }

    public static IEnumerable<StationData> FilterGermany(List<StationData> stations)
    {
        string codesFile =
        Path.Combine(AppContext.BaseDirectory, "mosmix_codes.txt");

        if (!File.Exists(codesFile))
            throw new FileNotFoundException(
            $"Datei nicht gefunden: {codesFile}");

        var germanCodes = new HashSet<string>(
        File.ReadAllLines(codesFile)
        .Where(x => !string.IsNullOrWhiteSpace(x))
        .Select(x => x.Trim()),
        StringComparer.OrdinalIgnoreCase);

        return stations.Where(s =>
        !string.IsNullOrWhiteSpace(s.Code) &&
        (
        germanCodes.Contains(s.Code) ||
        germanCodes.Contains(s.Name)
        )
        );
    }

    public Dictionary<DateTime, double> ComputeGermanyDailySunHours(List<StationData> stations)
    {
        var germanStations = FilterGermany(stations).ToList();
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var daily = new Dictionary<DateTime, double>();
            foreach (var kv in st.SunshineSecondsPerHour)
            {
                var day = kv.Key.Date;
                if (!daily.ContainsKey(day))
                    daily[day] = 0;
                daily[day] += kv.Value;
            }
            stationDaily[st.StationId] = daily;
        }

        var result = new Dictionary<DateTime, double>();
        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily.Where(s => s.Value.ContainsKey(day))
                                     .Select(s => s.Value[day])
                                     .ToList();
            result[day] = values.Average() / 3600.0;
        }

        return result;
    }

    public Dictionary<DateTime, double> ComputeGermanyDailyRainMm(List<StationData> stations)
    {
        var germanStations = FilterGermany(stations).ToList();
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var daily = new Dictionary<DateTime, double>();
            foreach (var kv in st.RainMmPerHour)
            {
                var day = kv.Key.Date;
                if (!daily.ContainsKey(day))
                    daily[day] = 0;
                daily[day] += kv.Value;
            }
            stationDaily[st.StationId] = daily;
        }

        var result = new Dictionary<DateTime, double>();
        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily.Where(s => s.Value.ContainsKey(day))
                                     .Select(s => s.Value[day])
                                     .ToList();
            result[day] = values.Average();
        }

        return result;
    }

    public Dictionary<DateTime, double> ComputeGermanyDailyTempC(List<StationData> stations)
    {
        var germanStations = FilterGermany(stations).ToList();
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var dailyLists = new Dictionary<DateTime, List<double>>();
            foreach (var kv in st.TempCPerHour)
            {
                var day = kv.Key.Date;
                if (!dailyLists.ContainsKey(day))
                    dailyLists[day] = new List<double>();
                dailyLists[day].Add(kv.Value);
            }

            var dailyMeans = new Dictionary<DateTime, double>();
            foreach (var kv in dailyLists)
                dailyMeans[kv.Key] = kv.Value.Average();

            stationDaily[st.StationId] = dailyMeans;
        }

        var result = new Dictionary<DateTime, double>();
        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily.Where(s => s.Value.ContainsKey(day))
                                     .Select(s => s.Value[day])
                                     .ToList();
            if (values.Count > 0)
                result[day] = values.Average();
        }

        return result;
    }

    public Dictionary<DateTime, List<(string Station, double Tmax)>>
    ComputeTop10DailyMaxTempForTodayAndTomorrow(List<StationData> stations)
    {
        var result = new Dictionary<DateTime, List<(string Station, double Tmax)>>();

        DateTime today = DateTime.UtcNow.Date;
        DateTime tomorrow = today.AddDays(1);

        var targets = new[] { today, tomorrow };

        foreach (var day in targets)
        {
            var list = new List<(string Station, double Tmax)>();

            foreach (var st in stations)
            {
                double tmax;

                if (st.DailyMaxTemp.TryGetValue(day, out double txValue))
                {
                    tmax = txValue;
                }
                else
                {
                    var values = st.TempCPerHour
                                   .Where(kv => kv.Key.Date == day)
                                   .Select(kv => kv.Value)
                                   .ToList();

                    if (values.Count == 0)
                        continue;

                    tmax = values.Max();
                }

                list.Add((st.Name, tmax));
            }

            var top10 = list
                .OrderByDescending(x => x.Tmax)
                .Take(10)
                .ToList();

            result[day] = top10;
        }

        return result;
    }
}