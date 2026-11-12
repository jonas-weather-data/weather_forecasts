using System;
using System.Collections.Generic;
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

    static async Task RunForecastAsync()
    {
        Environment.CurrentDirectory = AppContext.BaseDirectory;

        // TEST...
        //using var client_test = new HttpClient();

        //try
        //{
        //    var result = await client_test.GetStringAsync(
        //    "https://api.open-meteo.com/v1/forecast?latitude=50&longitude=7&daily=precipitation_sum&forecast_days=1");

        //    Console.WriteLine("TEST OK");
        //}
        //catch (Exception ex)
        //{
        //    Console.WriteLine(ex.ToString());
        //}
        // ...TEST

        DateTime today = DateTime.Today;

        string? run = DetectRun();

        if (run == null)
            return;

        using var client = new HttpClient();
        client.Timeout = TimeSpan.FromSeconds(60);

        var mosmixService = new MosmixService(run);
        var mosmix = mosmixService.LoadMosmixDataLatest(today);

        var omService = new OpenMeteoService(client, ModelIds);
        var omData = await omService.LoadOpenMeteoData(today);

        var sunDiagramService = new SunDiagramService(run);
        var rainDiagramService = new RainDiagramService(run);
        var tempDiagramService = new TempDiagramService(run);

        sunDiagramService.CreateSunDiagram(mosmix, today);
        rainDiagramService.CreateRainDiagram(mosmix, omData, today);
        tempDiagramService.CreateTempDiagram(mosmix, omData, today);
    }

    static async Task Main()
    {
        await RunForecastAsync();
    }
}