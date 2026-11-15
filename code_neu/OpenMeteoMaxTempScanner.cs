using System.Globalization;
using System.Text.Json;

public class OpenMeteoMaxTempScanner
{
    private readonly HttpClient _client;
    private readonly Dictionary<string, string> _modelIds;
    private readonly SemaphoreSlim _sem = new SemaphoreSlim(5);

    public OpenMeteoMaxTempScanner(HttpClient client, Dictionary<string, string> modelIds)
    {
        _client = client;
        _modelIds = modelIds;
    }

    private async Task<string> SafeGet(string url)
    {
        for (int i = 1; i <= 3; i++)
        {
            try
            {
                await _sem.WaitAsync();
                return await _client.GetStringAsync(url);
            }
            catch
            {
                if (i == 3) throw;
                await Task.Delay(1500);
            }
            finally
            {
                _sem.Release();
            }
        }
        throw new Exception("Unreachable");
    }

    // ⭐ KORREKT: echte Tagesmaxima
    private async Task<Dictionary<DateTime, double>> FetchDailyMaxTemp(double lat, double lon, string modelParam)
    {
        string url =
            $"https://api.open-meteo.com/v1/forecast" +
            $"?latitude={lat.ToString(CultureInfo.InvariantCulture)}" +
            $"&longitude={lon.ToString(CultureInfo.InvariantCulture)}" +
            $"&models={modelParam}" +
            $"&daily=temperature_2m_max" +
            $"&timezone=Europe/Berlin" +
            $"&forecast_days=16";

        string json = await SafeGet(url);

        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        if (root.ValueKind == JsonValueKind.Array && root.GetArrayLength() > 0)
            root = root[0];

        if (!root.TryGetProperty("daily", out var daily))
            return new();

        var timeArr = daily.GetProperty("time").EnumerateArray().ToList();
        var tmaxArr = daily.GetProperty("temperature_2m_max").EnumerateArray().ToList();

        var result = new Dictionary<DateTime, double>();
        for (int i = 0; i < timeArr.Count; i++)
        {
            if (tmaxArr[i].ValueKind == JsonValueKind.Null)
                continue;

            var date = DateTime.Parse(timeArr[i].GetString()!, CultureInfo.InvariantCulture).Date;
            result[date] = tmaxArr[i].GetDouble();
        }

        return result;
    }

    // ⭐ KORREKT: feineres Grid (0.25°)
    private List<(double lat, double lon)> BuildFineGrid()
    {
        var list = new List<(double, double)>();

        for (double lat = 47.0; lat <= 55.0; lat += 0.25)
            for (double lon = 5.5; lon <= 15.5; lon += 0.25)
                list.Add((lat, lon));

        return list;
    }

    public async Task PrintMaxTempsForAllModels()
    {
        var grid = BuildFineGrid();

        foreach (var model in _modelIds)
        {
            string modelName = model.Key;
            string modelParam = model.Value;

            Console.WriteLine();
            Console.WriteLine($"=== Höchste Tageshöchstwerte für Modell {modelName} ===");

            var bestPerDay = new Dictionary<DateTime, (double tmax, double lat, double lon)>();
            var lockObj = new object();

            var tasks = grid.Select(async point =>
            {
                var (lat, lon) = point;

                Dictionary<DateTime, double> dailyMax;
                try
                {
                    dailyMax = await FetchDailyMaxTemp(lat, lon, modelParam);
                }
                catch
                {
                    return;
                }

                lock (lockObj)
                {
                    foreach (var kv in dailyMax)
                    {
                        var day = kv.Key;
                        var tmax = kv.Value;

                        if (!bestPerDay.ContainsKey(day) || tmax > bestPerDay[day].tmax)
                            bestPerDay[day] = (tmax, lat, lon);
                    }
                }
            });

            await Task.WhenAll(tasks);

            foreach (var kv in bestPerDay.OrderBy(k => k.Key))
            {
                Console.WriteLine(
                    $"{kv.Key:dd.MM.yyyy}: {kv.Value.tmax:F1} °C  @ lat={kv.Value.lat:F2}, lon={kv.Value.lon:F2}");
            }
        }
    }
}
