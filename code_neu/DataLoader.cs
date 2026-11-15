using System.Text.Json;

public static class DataLoader
{
    public static ClimateData LoadClimateData()
    {
        var json = File.ReadAllText("climate_data.json");
        return JsonSerializer.Deserialize<ClimateData>(json)
        ?? throw new InvalidOperationException("climate_data.json konnte nicht geladen werden.");
    }

    public static ObservedData LoadObservedData()
    {
        var json = File.ReadAllText("observed_data.json");
        return JsonSerializer.Deserialize<ObservedData>(json)
        ?? throw new InvalidOperationException("observed_data.json konnte nicht geladen werden.");
    }
}