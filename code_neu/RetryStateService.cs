using System;
using System.IO;
using System.Text.Json;

public class RetryStateService
{
    private const string FileName = "runstate.json";

    public RetryState Load()
    {
        try
        {
            if (!File.Exists(FileName))
            {
                return new RetryState();
            }

            string json = File.ReadAllText(FileName);

            return JsonSerializer.Deserialize<RetryState>(json)
                   ?? new RetryState();
        }
        catch
        {
            return new RetryState();
        }
    }

    public void Save(RetryState state)
    {
        var json = JsonSerializer.Serialize(
            state,
            new JsonSerializerOptions
            {
                WriteIndented = true
            });

        File.WriteAllText(FileName, json);
    }
}
