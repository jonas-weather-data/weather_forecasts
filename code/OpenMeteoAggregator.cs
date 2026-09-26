using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

public class OpenMeteoAggregator
{

    private readonly HttpClient _client;
    private readonly Dictionary<string, string> _modelIds;
    private readonly SemaphoreSlim _semaphore = new SemaphoreSlim(5); // max. 5 gleichzeitige Requests

    public OpenMeteoAggregator(HttpClient client, Dictionary<string, string> modelIds)
    {
        var handler = new SocketsHttpHandler
        {
            AutomaticDecompression = DecompressionMethods.All,
            AllowAutoRedirect = true,
            UseCookies = false,
            PooledConnectionLifetime = TimeSpan.FromMinutes(2),
            PooledConnectionIdleTimeout = TimeSpan.FromSeconds(30),
            MaxConnectionsPerServer = 2
        };

        _client = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromMinutes(2)
        };

        _client.DefaultRequestHeaders.UserAgent.ParseAdd(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/124.0 Safari/537.36");

        _client.DefaultRequestHeaders.ConnectionClose = true;

        _modelIds = modelIds;
    }


    public static List<(double lat, double lon)> BuildGermanyGrid()
    {
        var list = new List<(double, double)>();

        for (double lat = 47.5; lat <= 54.5; lat += 1.0)
            for (double lon = 6.0; lon <= 14.5; lon += 1.0)
            {
                // Nordsee
                if (lat >= 54.0 && lon <= 8.5)
                    continue;

                // Ostsee
                if (lat >= 54.0 && lon >= 12.0)
                    continue;

                // Dänemark (nur die eine 55°-Zelle)
                if (lat >= 55.0)
                    continue;

                // Niederlande (nur die 52°/6°-Zelle)
                if (lat >= 52.0 && lon <= 6.5)
                    continue;

                // Polen (nur die 53°/14°-Zelle)
                if (lat >= 53.0 && lon >= 14.0)
                    continue;

                list.Add((lat, lon));
            }

        //return list;
        return new List<(double lat, double lon)>
        {
        (54.5, 8.5),
        (54.0, 11.0),
        (53.5, 8.5),
        (53.0, 13.5),
        (52.5, 7.5),
        (52.5, 13.5),
        (51.0, 6.5),
        (51.0, 10.5),
        (50.0, 12.5),
        (49.5, 8.5),
        (48.5, 11.5),
        (47.5, 13.0)
        };
    }

    // ------------------------------------------------------------
    // Zentrale HTTP-Methode mit Timeout/Retry + begrenzter Parallelität
    // ------------------------------------------------------------
    private async Task<string> SafeGetStringAsync(string url)
    {
        for (int attempt = 1; attempt <= 5; attempt++) // 1 Versuch + 4 Retry
        {
            try
            {
                await _semaphore.WaitAsync();
                using var response = await _client.GetAsync(url);

                Console.WriteLine($"{response.StatusCode} {url}");

                response.EnsureSuccessStatusCode();

                return await response.Content.ReadAsStringAsync();
            }
            catch (Exception ex)
            {
                Console.WriteLine($"HTTP-Fehler (Versuch {attempt}/5): {ex.ToString()}");
                if (attempt == 5)
                    throw; // beim letzten Versuch Fehler weiterwerfen
                await Task.Delay(10000);
            }
            finally
            {
                _semaphore.Release();
            }
        }

        // sollte nie erreicht werden
        throw new Exception("Unbekannter Fehler in SafeGetStringAsync.");
    }

    public async Task<Dictionary<string, Dictionary<DateTime, (double rain, int count)>>> AggregateRainAsync(
        List<(double lat, double lon)> grid,
        List<DateTime> targetDates)
    {
        var agg = new Dictionary<string, Dictionary<DateTime, (double rain, int count)>>();

        foreach (var model in _modelIds.Keys)
            agg[model] = targetDates.ToDictionary(d => d, d => (0.0, 0));

        foreach (var model in _modelIds)
        {
            string modelName = model.Key;
            string modelParam = model.Value;

            var perDate = agg[modelName];
            var lockObj = new object();

            var tasks = grid.Select(async point =>
            {
                var (lat, lon) = point;

                Dictionary<DateTime, double> dailyData;
                try
                {
                    dailyData = await FetchDailyRainForPoint(lat, lon, modelParam);
                    int runHourUtc = DateTime.UtcNow.Hour;
                    DateTime runDateUtc = DateTime.UtcNow.Date;

                    dailyData = Apply06zLimit(modelName, dailyData);
                }
                catch
                {
                    // diesen Punkt überspringen, wenn er nicht lieferbar ist
                    return;
                }

                lock (lockObj)
                {
                    foreach (var kvp in dailyData)
                    {
                        var date = kvp.Key;
                        var rain = kvp.Value;

                        if (!perDate.ContainsKey(date))
                            continue;

                        var current = perDate[date];
                        current.rain += rain;
                        current.count++;
                        perDate[date] = current;
                    }
                }
            });

            await Task.WhenAll(tasks);
        }

        return agg;
    }

    public async Task<Dictionary<string, Dictionary<DateTime, (double temp, int count)>>> AggregateTempAsync(
        List<(double lat, double lon)> grid,
        List<DateTime> targetDates)
    {
        var tzBerlin = TimeZoneInfo.FindSystemTimeZoneById("Europe/Berlin");
        var normalizedDates = targetDates
            .Select(d => TimeZoneInfo.ConvertTime(d, tzBerlin).Date)
            .Distinct()
            .ToList();

        var agg = new Dictionary<string, Dictionary<DateTime, (double temp, int count)>>();

        foreach (var model in _modelIds.Keys)
            agg[model] = normalizedDates.ToDictionary(d => d, d => (0.0, 0));

        foreach (var model in _modelIds)
        {
            string modelName = model.Key;
            string modelParam = model.Value;

            var perDate = agg[modelName];
            var lockObj = new object();

            var tasks = grid.Select(async point =>
            {
                var (lat, lon) = point;

                Dictionary<DateTime, double> dailyData;
                try
                {
                    dailyData = await FetchDailyTempForPoint(lat, lon, modelParam);
                    int runHourUtc = DateTime.UtcNow.Hour;
                    DateTime runDateUtc = DateTime.UtcNow.Date;

                    dailyData = Apply06zLimit(modelName, dailyData);
                }
                catch
                {
                    // diesen Punkt überspringen, wenn er nicht lieferbar ist
                    return;
                }

                lock (lockObj)
                {
                    foreach (var kvp in dailyData)
                    {
                        var date = kvp.Key.Date;

                        if (!perDate.ContainsKey(date))
                            continue;

                        var current = perDate[date];
                        current.temp += kvp.Value;
                        current.count++;
                        perDate[date] = current;
                    }
                }
            });

            await Task.WhenAll(tasks);
        }

        return agg;
    }

    public static (double[] days, double[] values) BuildCumulativeSeries(
        Dictionary<DateTime, (double value, int count)> daily,
        double startValue)
    {
        var listDays = new List<double>();
        var listVals = new List<double>();

        double cum = startValue;

        foreach (var kvp in daily.OrderBy(k => k.Key))
        {
            if (kvp.Value.count == 0)
                continue;

            double add = kvp.Value.value / kvp.Value.count;
            cum += add;

            listDays.Add(kvp.Key.Day);
            listVals.Add(cum);
        }

        return (listDays.ToArray(), listVals.ToArray());
    }

    private async Task<Dictionary<DateTime, double>> FetchDailyRainForPoint(
        double lat, double lon, string modelParam)
    {
        string url =
            $"https://api.open-meteo.com/v1/forecast" +
            $"?latitude={lat.ToString(CultureInfo.InvariantCulture)}" +
            $"&longitude={lon.ToString(CultureInfo.InvariantCulture)}" +
            $"&models={modelParam}" +
            $"&daily=precipitation_sum" +
            $"&timezone=Europe/Berlin" +
            $"&forecast_days=16";

        Console.WriteLine(url);
        string json = await SafeGetStringAsync(url);

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
            root = root[0];

        if (!root.TryGetProperty("daily", out var daily))
            return new();

        var timeDaily = daily.GetProperty("time").EnumerateArray().ToList();
        var rainArr = daily.GetProperty("precipitation_sum").EnumerateArray().ToList();

        var result = new Dictionary<DateTime, double>();
        for (int i = 0; i < timeDaily.Count; i++)
        {
            var date = DateTime.Parse(timeDaily[i].GetString()!).Date;
            double rainMm = rainArr[i].ValueKind == JsonValueKind.Null ? 0.0 : rainArr[i].GetDouble();
            result[date] = rainMm;
        }

        return result;
    }

    private async Task<Dictionary<DateTime, double>> FetchDailyTempForPoint(
        double lat, double lon, string modelParam)
    {
        string url =
            $"https://api.open-meteo.com/v1/forecast" +
            $"?latitude={lat.ToString(CultureInfo.InvariantCulture)}" +
            $"&longitude={lon.ToString(CultureInfo.InvariantCulture)}" +
            $"&models={modelParam}" +
            $"&hourly=temperature_2m" +
            $"&timezone=Europe/Berlin" +
            $"&forecast_days=16";

        Console.WriteLine(url);
        string json = await SafeGetStringAsync(url);

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
            root = root[0];

        if (!root.TryGetProperty("hourly", out var hourly))
            return new();

        var timeArr = hourly.GetProperty("time").EnumerateArray().ToList();
        var tempArr = hourly.GetProperty("temperature_2m").EnumerateArray().ToList();

        var result = new Dictionary<DateTime, double>();
        var buckets = new Dictionary<DateTime, List<double>>();

        for (int i = 0; i < timeArr.Count; i++)
        {
            var dtLocal = DateTime.Parse(timeArr[i].GetString()!, CultureInfo.InvariantCulture);
            var day = dtLocal.Date;

            // Nur Stunden verwenden, die wirklich zu diesem Kalendertag gehören
            if (dtLocal.Date != day)
                continue;


            if (!buckets.TryGetValue(day, out var list))
            {
                list = new List<double>();
                buckets[day] = list;
            }

            if (tempArr[i].ValueKind != JsonValueKind.Null)
                list.Add(tempArr[i].GetDouble());
        }

        foreach (var kv in buckets)
        {
            if (kv.Value.Count > 21) // nur (nahezu) vollständige Tage
                result[kv.Key] = kv.Value.Average();
        }

        return result;
    }
    
    public static string DetectModelRun(
        Dictionary<DateTime, (double value, int count)> daily,
        string modelName,
        DateTime firstUtc)
    {
        if (daily == null || daily.Count == 0)
            return $"{modelName}: keine Daten";

        int hour = firstUtc.Hour;

        int runHour = hour switch
        {
            >= 0 and < 6 => 0,
            >= 6 and < 12 => 6,
            >= 12 and < 18 => 12,
            _ => 18
        };

        DateTime runTime = new DateTime(
            firstUtc.Year,
            firstUtc.Month,
            firstUtc.Day,
            runHour,
            0,
            0,
            DateTimeKind.Utc
        );

        return $"{modelName}: Modelllauf {runTime:dd.MM.yyyy HH:mm} UTC";
    }

    private static readonly Dictionary<string, TimeSpan?> ModelLimits06z = new()
{
    { "GFS",    null },                 // nicht begrenzen
    { "AIFS",   null },                 // nicht begrenzen
    { "MOSMIX", null },                 // nicht begrenzen
    { "ICON",   TimeSpan.FromHours(120) },  // bis +120h
    { "UKMO",   TimeSpan.Zero },            // komplett ignorieren
    { "IFS",    TimeSpan.FromHours(144) },  // bis +144h
    { "GEM",    TimeSpan.Zero }             // komplett ignorieren
};

    private static Dictionary<DateTime, double> Apply06zLimit(
    string modelName,
    Dictionary<DateTime, double> daily)
    {
        // 06z gilt lokal zwischen 12 und 16 Uhr
        int h = DateTime.Now.Hour;
        bool is06z = h >= 12 && h <= 16;

        if (!is06z)
            return daily;

        // Modellgrenzen exakt nach deiner Vorgabe
        TimeSpan? limit = modelName switch
        {
            "GFS" => null,                     // nicht begrenzen
            "AIFS" => null,                     // nicht begrenzen
            "MOSMIX" => null,                     // nicht begrenzen
            "ICON" => TimeSpan.FromHours(120),  // bis +120h
            "IFS" => TimeSpan.FromHours(144),  // bis +144h
            "UKMO" => TimeSpan.Zero,            // komplett ignorieren
            "GEM" => TimeSpan.Zero,            // komplett ignorieren
            _ => null
        };

        // Modelle ohne 06z-Lauf → komplett ignorieren
        if (limit == TimeSpan.Zero)
            return new Dictionary<DateTime, double>();

        // Modelle ohne Begrenzung
        if (limit is null)
            return daily;

        // Begrenzung anwenden
        double days = limit.Value.TotalHours / 24.0;
        DateTime maxValidDate = DateTime.UtcNow.Date.AddDays(days);

        return daily
            .Where(kvp => kvp.Key.Date <= maxValidDate)
            .ToDictionary(kvp => kvp.Key, kvp => kvp.Value);
    }


    public static void PrintMonthlyAverages(
        Dictionary<string, Dictionary<DateTime, (double value, int count)>> data,
        string label)
    {
        Console.Write($"{label}: ");

        foreach (var model in data.Keys)
        {
            var daily = data[model];

            double sum = 0;
            int days = 0;

            foreach (var kv in daily)
            {
                if (kv.Value.count > 0)
                {
                    sum += kv.Value.value / kv.Value.count;
                    days++;
                }
            }

            double avg = days > 0 ? sum / days : 0.0;

            Console.Write($"{model}: {avg:F1}  ");
        }

        Console.WriteLine();
    }
}
