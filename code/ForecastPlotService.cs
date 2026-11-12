using System;
using System.Collections.Generic;
using System.Linq;
using OxyPlot;
using OxyPlot.Axes;
using OxyPlot.Series;
using OxyPlot.SkiaSharp;
using System.IO;

public class ForecastPlotService
{
    private readonly ForecastEvaluator _evaluator = new();

    public void PlotLeadTimeDiagram(int year, int month, string outputPath)
    {
        // 1) Fehlerdaten laden
        var errors = _evaluator.EvaluateMonth(year, month);

        // 2) Modelle extrahieren
        var modelle = errors.Select(e => e.Modell).Distinct().OrderBy(x => x).ToList();

        // 3) Vorhersagetage 1–15
        var leadTimes = Enumerable.Range(1, 15).ToList();

        // 4) OxyPlot-Model
        var model = new PlotModel
        {
            Title = $"Modellgüte nach Vorhersagetag – {month:00}/{year}",
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent
        };

        // X-Achse: Vorhersagetag
        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Bottom,
            Minimum = 1,
            Maximum = 15,
            MajorStep = 1,
            Title = "Vorhersagetag",
            TitleFontSize = 20,
            FontSize = 16
        });

        // Y-Achse: Fehler
        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Left,
            Title = "Fehler (°C)",
            TitleFontSize = 20,
            FontSize = 16,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = ModelColors.MajorGridline,
            MinorGridlineColor = ModelColors.MinorGridlineColor
        });

        // 5) Farben pro Modell
        var farben = new Dictionary<string, OxyColor>(StringComparer.OrdinalIgnoreCase)
        {
            ["ICON"] = ModelColors.Icon,
            ["GFS"] = ModelColors.Gfs,
            ["IFS"] = ModelColors.Ifs,
            ["AIFS"] = ModelColors.AIFS,
            ["UKMO"] = ModelColors.UKMO,
            ["GEM"] = ModelColors.GEM,
            ["MOSMIX"] = ModelColors.Mosmix
        };

        // 6) Für jedes Modell eine Linie erzeugen
        foreach (var modell in modelle)
        {
            var serie = new LineSeries
            {
                Title = modell,
                Color = farben.ContainsKey(modell) ? farben[modell] : OxyColors.Black,
                StrokeThickness = 2,
                MarkerType = MarkerType.Circle,
                MarkerSize = 3
            };

            foreach (var lt in leadTimes)
            {
                var werte = errors
                    .Where(e => e.Modell == modell && e.VorhersageTag == lt)
                    .Select(e => Math.Abs((double)e.Fehler))
                    .ToList();

                if (werte.Count == 0)
                    continue;

                double meanError = werte.Average();

                serie.Points.Add(new DataPoint(lt, meanError));
            }

            model.Series.Add(serie);
        }

        // 7) Export als PNG
        using var stream = File.Create(outputPath);
        var exporter = new PngExporter
        {
            Width = 1200,
            Height = 700,
            Dpi = 96
        };
        exporter.Export(model, stream);
    }
}
