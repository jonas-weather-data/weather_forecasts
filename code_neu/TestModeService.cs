using System;
using System.Collections.Generic;

public class TestModeService
{
    private readonly TestModeDataBuilder _dataBuilder = new();
    private readonly TestModeForecastWriter _writer = new();
    private readonly ForecastPlotService _plotService = new();
    private readonly ObservationRepository _obsRepo = new();

    public void Run()
    {
        DateTime today = _dataBuilder.Today;
        int year = today.Year;
        int month = today.Month;

        Console.WriteLine("Testmode gestartet.");

        var mosmixData = _dataBuilder.BuildMosmixData();
        Console.WriteLine("MOSMIX-Testdaten erzeugt.");

        var (temp, rain, sun) = _dataBuilder.BuildModelData();
        Console.WriteLine("Hardcoded Modellprognosen erzeugt.");

        _writer.WriteForecasts(today, temp, rain, sun);
        Console.WriteLine("Prognosen in modellprognosen_testmode gespeichert.");

        var omData = BuildOpenMeteoDataObject(temp, rain, sun);

        new TempDiagramService("00z").CreateTempDiagram(mosmixData, omData, today);
        new SunDiagramService("00z").CreateSunDiagram(mosmixData, today);
        new RainDiagramService("00z").CreateRainDiagram(mosmixData, omData, today);

        Console.WriteLine("Prognosediagramme erzeugt.");

        var observed = _obsRepo.GetObservedTmk(year, month);
        Console.WriteLine("Beobachtungen aus tagesmittel_2 geladen.");

        new TestModeForecastEvaluator().PlotLeadTimeDiagrams(year, month);

        Console.WriteLine("Leadtime-Diagramme erzeugt.");
        Console.WriteLine("Testmode abgeschlossen.");
    }

    private OpenMeteoData BuildOpenMeteoDataObject(
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> temp,
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> rain,
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> sun)
    {
        var tempConv = Convert(temp);
        var rainConv = Convert(rain);

        return new OpenMeteoData
        {
            Temp = tempConv,
            Rain = rainConv,
            IconFirstUtc = new DateTime(2026, 6, 9, 0, 0, 0, DateTimeKind.Utc),
            GfsFirstUtc = new DateTime(2026, 6, 1, 6, 0, 0, DateTimeKind.Utc),
            IfsFirstUtc = new DateTime(2026, 6, 5, 12, 0, 0, DateTimeKind.Utc),
            AifsFirstUtc = new DateTime(2026, 6, 14, 0, 0, 0, DateTimeKind.Utc),
            UkmoFirstUtc = new DateTime(2026, 6, 10, 18, 0, 0, DateTimeKind.Utc),
            GemFirstUtc = new DateTime(2026, 6, 14, 6, 0, 0, DateTimeKind.Utc)
        };
    }

    private Dictionary<string, Dictionary<DateTime, (double, int)>> Convert(
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> src)
    {
        var result = new Dictionary<string, Dictionary<DateTime, (double, int)>>();

        foreach (var model in src.Keys)
        {
            var inner = new Dictionary<DateTime, (double, int)>();
            foreach (var kv in src[model])
                inner[kv.Key] = (kv.Value.val, kv.Value.count);

            result[model] = inner;
        }

        return result;
    }
}
