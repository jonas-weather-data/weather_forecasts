using System.Text.Json;

public class ForecastRepository
{
    public void InsertForecast(
    DateTime datum,
    string modell,
    int vorhersageTag,
    decimal? tmkPrognose,
    decimal? sdkPrognose,
    decimal? rskPrognose)
    {
        string key = $"{datum:yyyy-MM-dd}_{modell}_{vorhersageTag}";

        if (tmkPrognose.HasValue)
            SaveValue("00z_prognose_temp.json", key, tmkPrognose.Value);

        if (sdkPrognose.HasValue)
            SaveValue("00z_prognose_sun.json", key, sdkPrognose.Value);

        if (rskPrognose.HasValue)
            SaveValue("00z_prognose_rain.json", key, rskPrognose.Value);
    }

    private static void SaveValue(
    string fileName,
    string key,
    decimal value)
    {
        Dictionary<string, decimal> data;

        if (File.Exists(fileName))
        {
            data = JsonSerializer.Deserialize<Dictionary<string, decimal>>(
            File.ReadAllText(fileName))
            ?? new Dictionary<string, decimal>();
        }
        else
        {
            data = new Dictionary<string, decimal>();
        }

        data[key] = value;

        File.WriteAllText(
        fileName,
        JsonSerializer.Serialize(
        data,
        new JsonSerializerOptions
        {
            WriteIndented = true
        }));
    }
}