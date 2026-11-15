using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading.Tasks;

class Program
{
    private static readonly Dictionary<string, string> ModelIds = new()
    {
        { "ICON", "icon_seamless" },
        { "GFS", "gfs_seamless" },
        { "IFS", "ecmwf_ifs025" },
        { "AIFS", "ecmwf_aifs025_single" },
        { "UKMO", "ukmo_seamless" },
        { "GEM" , "gem_global" }
    };

    private static string DetectRun()
    {
        var tzBerlin = TimeZoneInfo.FindSystemTimeZoneById("Europe/Berlin");
        var t = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tzBerlin).TimeOfDay;

        if (t < new TimeSpan(12, 0, 0))
            return "00z";

        if (t < new TimeSpan(19, 0, 0))
            return "06z";

        return "12z";
    }

    private static DateTime DetectRunUtc()
    {
        var tzBerlin = TimeZoneInfo.FindSystemTimeZoneById("Europe/Berlin");
        var nowBerlin = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tzBerlin);

        int runHour =
            nowBerlin.TimeOfDay < new TimeSpan(12, 0, 0) ? 0 :
            nowBerlin.TimeOfDay < new TimeSpan(19, 0, 0) ? 6 :
            12;

        return new DateTime(
            nowBerlin.Year,
            nowBerlin.Month,
            nowBerlin.Day,
            runHour,
            0,
            0,
            DateTimeKind.Utc);
    }

    static async Task RunForecastAsync()
    {
        Environment.CurrentDirectory = AppContext.BaseDirectory;

        DateTime today = DateTime.Today;

        string run = DetectRun();
        DateTime runUtc = DetectRunUtc();

        using var client = new HttpClient();
        client.Timeout = TimeSpan.FromSeconds(60);

        var availabilityService =
            new ModelRunAvailabilityService(client);

        ForecastStatus forecastStatus =
            await availabilityService.CheckRunAsync(
                ModelIds,
                runUtc);

        Console.WriteLine();
        Console.WriteLine("======================================");
        Console.WriteLine($"Run: {run}");
        Console.WriteLine($"Run UTC: {runUtc:yyyy-MM-dd HH:mm}");
        Console.WriteLine($"Verfügbarkeit: {forecastStatus.PercentAvailable:F1}%");
        Console.WriteLine("======================================");

        foreach (var model in forecastStatus.ModelStatuses)
        {
            Console.WriteLine(
                $"{model.ModelName}: " +
                $"{model.AvailableHours}/{model.ExpectedHours} " +
                $"Complete={model.Complete}");
        }

        var availableModels =
            forecastStatus.ModelStatuses
            .Where(x => x.Complete)
            .Select(x => x.ModelName)
            .ToList();

        Console.WriteLine();
        Console.WriteLine("Verwendete Modelle:");

        foreach (var model in availableModels)
        {
            Console.WriteLine($" - {model}");
        }

        if (availableModels.Count == 0)
        {
            Console.WriteLine();
            Console.WriteLine("Kein Modell vollständig verfügbar.");
            return;
        }

        var mosmixService = new MosmixService(run);
        var mosmix = mosmixService.LoadMosmixDataLatest(today);

        var omService = new OpenMeteoService(
            client,
            ModelIds);

        var omData =
            await omService.LoadOpenMeteoData(
                today,
                availableModels);

        var sunDiagramService = new SunDiagramService(run);
        var rainDiagramService = new RainDiagramService(run);
        var tempDiagramService = new TempDiagramService(run);

        sunDiagramService.CreateSunDiagram(
            mosmix,
            today);

        rainDiagramService.CreateRainDiagram(
            mosmix,
            omData,
            today);

        tempDiagramService.CreateTempDiagram(
            mosmix,
            omData,
            today);
    }

    static async Task Main()
    {
        await RunForecastAsync();
    }
}
