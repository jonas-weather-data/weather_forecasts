using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading.Tasks;

public class ModelRunAvailabilityService
{
    private readonly HttpClient _client;

    private static readonly Dictionary<string, int> ExpectedHours = new()
    {
        { "ICON", 180 },
        { "GFS", 384 },
        { "IFS", 360 },
        { "AIFS", 360 },
        { "UKMO", 168 },
        { "GEM", 240 }
    };

    public ModelRunAvailabilityService(HttpClient client)
    {
        _client = client;
    }

    public async Task<ForecastStatus> CheckRunAsync(
        Dictionary<string, string> modelIds,
        DateTime runUtc)
    {
        var result = new ForecastStatus();

        int expectedHoursTotal = 0;
        int availableHoursTotal = 0;

        foreach (var model in modelIds)
        {
            string modelName = model.Key;
            string modelId = model.Value;

            int expectedHours = ExpectedHours[modelName];

            expectedHoursTotal += expectedHours;

            var modelStatus = await CheckModelAsync(
                modelName,
                modelId,
                runUtc,
                expectedHours);

            result.ModelStatuses.Add(modelStatus);

            availableHoursTotal += Math.Min(
                modelStatus.AvailableHours,
                expectedHours);

            if (!modelStatus.Complete)
            {
                result.MissingModels.Add(modelName);
            }
        }

        result.ExpectedHours = expectedHoursTotal;
        result.AvailableHours = availableHoursTotal;

        result.PercentAvailable =
            expectedHoursTotal > 0
            ? 100.0 * availableHoursTotal / expectedHoursTotal
            : 0.0;

        result.AllDataAvailable =
            result.ModelStatuses.All(x => x.Complete);

        return result;
    }

    private async Task<ModelRunStatus> CheckModelAsync(
        string modelName,
        string modelId,
        DateTime runUtc,
        int expectedHours)
    {
        var status = new ModelRunStatus
        {
            ModelName = modelName,
            ExpectedHours = expectedHours
        };

        try
        {
            string runString =
                runUtc.ToString(
                    "yyyy-MM-dd'T'HH:mm",
                    CultureInfo.InvariantCulture);

            string url =
                "https://single-runs-api.open-meteo.com/v1/forecast" +
                $"?latitude=50.0" +
                $"&longitude=8.0" +
                $"&models={modelId}" +
                $"&run={runString}" +
                $"&hourly=temperature_2m" +
                $"&forecast_hours={expectedHours}" +
                $"&timezone=UTC";

            using var response = await _client.GetAsync(url);

            if (!response.IsSuccessStatusCode)
            {
                status.Complete = false;
                status.AvailableHours = 0;
                status.ErrorMessage = await response.Content.ReadAsStringAsync();
                return status;
            }

            string json = await response.Content.ReadAsStringAsync();

            using var doc = JsonDocument.Parse(json);

            var hourly = doc.RootElement.GetProperty("hourly");

            int availableHours =
                hourly
                .GetProperty("time")
                .EnumerateArray()
                .Count();

            status.AvailableHours = availableHours;
            status.Complete = availableHours >= expectedHours;

            return status;
        }
        catch (Exception ex)
        {
            status.Complete = false;
            status.AvailableHours = 0;
            status.ErrorMessage = ex.Message;

            return status;
        }
    }
}
