using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;

public class OpenMeteoService
{
    private readonly HttpClient _client;
    private readonly Dictionary<string, string> _modelIds;

    // Repository einbauen
    private readonly ForecastRepository _forecastRepo = new ForecastRepository();

    public OpenMeteoService(HttpClient client, Dictionary<string, string> modelIds)
    {
        _client = client;
        _modelIds = modelIds;
    }

    // ============================================================
    // HTTP GET mit Retry
    // ============================================================
    private async Task<string> SafeGetStringAsync(string url)
    {
        for (int attempt = 1; attempt <= 3; attempt++)
        {
            try
            {
                return await _client.GetStringAsync(url);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"HTTP-Fehler (Versuch {attempt}/3): {ex.Message}");
                await Task.Delay(2000);
            }
        }

        throw new Exception("Open-Meteo antwortet nicht nach 3 Versuchen.");
    }

    // ============================================================
    // 1) Erste Stunde eines Modells holen (UTC)
    // ============================================================
    public async Task<DateTime> FetchFirstHourlyUtc(double lat, double lon, string modelParam)
    {
        string url =
            $"https://api.open-meteo.com/v1/forecast" +
            $"?latitude={lat.ToString(CultureInfo.InvariantCulture)}" +
            $"&longitude={lon.ToString(CultureInfo.InvariantCulture)}" +
            $"&models={modelParam}" +
            $"&hourly=temperature_2m" +
            $"&timezone=UTC" +
            $"&forecast_days=1";

        string json = await SafeGetStringAsync(url);

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
            root = root[0];

        var hourly = root.GetProperty("hourly");
        var timeArr = hourly.GetProperty("time").EnumerateArray().ToList();

        return DateTime.Parse(timeArr[0].GetString()!, CultureInfo.InvariantCulture);
    }

    public async Task<OpenMeteoData> LoadOpenMeteoData(DateTime today)
    {
        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;
        int daysInMonth = DateTime.DaysInMonth(year, month);

        var grid = OpenMeteoAggregator.BuildGermanyGrid();
        var targetDates = Enumerable.Range(todayDay, daysInMonth - todayDay + 1)
                                    .Select(d => new DateTime(year, month, d))
                                    .ToList();

        var om = new OpenMeteoAggregator(_client, _modelIds);

        var aggRain = await om.AggregateRainAsync(grid, targetDates);
        var aggTemp = await om.AggregateTempAsync(grid, targetDates);

        var iconFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["ICON"]);
        var gfsFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["GFS"]);
        var ifsFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["IFS"]);
        var aifsFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["AIFS"]);
        var ukmoFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["UKMO"]);
        var gemFirstUtc = await FetchFirstHourlyUtc(51.0, 10.0, _modelIds["GEM"]);

        var data = new OpenMeteoData
        {
            Rain = aggRain,
            Temp = aggTemp,
            IconFirstUtc = iconFirstUtc,
            GfsFirstUtc = gfsFirstUtc,
            IfsFirstUtc = ifsFirstUtc,
            AifsFirstUtc = aifsFirstUtc,
            UkmoFirstUtc = ukmoFirstUtc,
            GemFirstUtc = gemFirstUtc
        };

        // HIER: Prognosen speichern
        Save00zForecastsToJson(data, today);

        return data;
    }

    // ============================================================
    // ⭐ Prognosen in JSON speichern
    // ============================================================
    private void Save00zForecastsToJson(OpenMeteoData data, DateTime today)
    {
        // Nur beim 00z-Lauf speichern
        if (DateTime.UtcNow.Hour >= 12)
            return;

        foreach (var model in data.Temp.Keys)
        {
            foreach (var kv in data.Temp[model])
            {
                var date = kv.Key;

                int vorhersageTag = (date - today.Date).Days;

                // Nur Tag 0 speichern
                if (vorhersageTag != 0)
                    continue;

                var (tempSum, tempCount) = kv.Value;

                decimal? tmk =
                tempCount > 0
                ? (decimal?)(tempSum / tempCount)
                : null;

                decimal? rsk = null;

                if (data.Rain.ContainsKey(model) &&
                data.Rain[model].TryGetValue(date, out var rain) &&
                rain.count > 0)
                {
                    rsk = (decimal?)(rain.rain / rain.count);
                }

                _forecastRepo.InsertForecast(
                date,
                model,
                vorhersageTag,
                tmk,
                null,
                rsk
                );
            }
        }
    }

    // ============================================================
    // Temperatur-Hilfsfunktion
    // ============================================================
    public (List<int> days, List<double> cumMeans, Dictionary<int, double> dayMeans)
    BuildTempSeries(
        Dictionary<DateTime, (double temp, int count)> modelData,
        int lastObsDay,
        double lastObsMean,
        int forecastStart,
        int maxDay,
        int year,
        int month,
        string modelName)
    {
        var days = new List<int>();
        var cumMeans = new List<double>();
        var dayMeans = new Dictionary<int, double>();

        int n = lastObsDay;
        double sum = lastObsMean * n;

        if (n > 0)
        {
            days.Add(lastObsDay);
            cumMeans.Add(lastObsMean);
        }

        foreach (var kv in modelData.OrderBy(k => k.Key))
        {
            if (kv.Key.Year != year || kv.Key.Month != month)
                continue;

            int d = kv.Key.Day;
            if (d < forecastStart || d > maxDay)
                continue;

            var (tempSum, count) = kv.Value;
            if (count <= 0)
                continue;

            double dayMean = tempSum / count;

            if (dayMean < -50.0 || dayMean > 60.0)
                continue;

            //if (modelName == "GFS")
            //    dayMean += 0.07;

            n++;
            sum += dayMean;
            double cumMean = sum / n;

            days.Add(d);
            cumMeans.Add(cumMean);
            dayMeans[d] = dayMean;
        }

        return (days, cumMeans, dayMeans);
    }
}

public class OpenMeteoData
{
    public Dictionary<string, Dictionary<DateTime, (double rain, int count)>> Rain { get; set; }
    public Dictionary<string, Dictionary<DateTime, (double temp, int count)>> Temp { get; set; }

    public DateTime IconFirstUtc { get; set; }
    public DateTime GfsFirstUtc { get; set; }
    public DateTime IfsFirstUtc { get; set; }
    public DateTime AifsFirstUtc { get; set; }
    public DateTime UkmoFirstUtc { get; set; }
    public DateTime GemFirstUtc { get; set; }
}
