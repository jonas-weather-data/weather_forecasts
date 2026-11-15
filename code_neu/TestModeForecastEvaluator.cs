using System;
using System.Collections.Generic;
using System.Linq;
using OxyPlot;
using OxyPlot.Axes;
using OxyPlot.Series;
using OxyPlot.Legends;
using OxyPlot.SkiaSharp;

public class TestModeForecastEvaluator
{
    public record ForecastPoint(
        DateTime Datum,
        string Modell,
        int VorhersageTag,
        double Prognose,
        double Beobachtung,
        double Fehler
    );

    private readonly TestModeDataBuilder _builder = new();

    public List<ForecastPoint> EvaluateMonth(int year, int month)
    {
        var (temp, _, _) = _builder.BuildModelData();
        var mosmix = _builder.BuildMosmixData();

        double beob15 = mosmix.ObservedTemp[14]; // 15. Juni
        beob15 = Math.Round(beob15, 2);

        var result = new List<ForecastPoint>();

        foreach (var model in temp.Keys)
        {
            foreach (var kv in temp[model])
            {
                var date = kv.Key;
                var (val, count) = kv.Value;

                double progn = count > 0 ? val / count : 0;
                double fehler = progn - beob15;

                int lt = 15 - date.Day; // Leadtime: 14 → 1

                result.Add(new ForecastPoint(
                    date,
                    model,
                    lt,
                    progn,
                    beob15,
                    fehler
                ));
            }
        }

        return result;
    }

    public void PlotLeadTimeDiagrams(int year, int month)
    {
        var data = EvaluateMonth(year, month);

        var dir = @"C:\Projekte\DWD\modellprognose\Verifikation\Test";
        Directory.CreateDirectory(dir);
        string ts = DateTime.Now.ToString("yyyyMMdd_HHmmss");

        ExportPlot(BuildForecastValueModel(data, year, month),
            Path.Combine(dir, $"leadtime_values_{year}_{month:00}_{ts}.png"));

        ExportPlot(BuildForecastErrorModel(data, year, month),
            Path.Combine(dir, $"leadtime_errors_{year}_{month:00}_{ts}.png"));
    }

    private PlotModel BuildForecastValueModel(List<ForecastPoint> data, int year, int month)
    {
        var model = CreateBaseModel(
            $"Prognoseentwicklung ({new DateTime(year, month, 1):MMMM yyyy})",
            "Temperatur (°C)");

        var farben = GetModelColors();

        var modelle = data.Select(e => e.Modell).Distinct().OrderBy(x => x);

        foreach (var modell in modelle)
        {
            var serie = CreateLineSeries(modell, farben);

            var grouped = data
                .Where(e => e.Modell == modell)
                .OrderBy(e => e.VorhersageTag);

            foreach (var g in grouped)
                serie.Points.Add(new DataPoint(g.VorhersageTag, g.Prognose));

            if (serie.Points.Count > 0)
                model.Series.Add(serie);
        }

        double obs = data.First().Beobachtung;

        var obsLine = new LineSeries
        {
            Title = $"Eingetroffen: {obs:F2}°C",
            Color = OxyColors.ForestGreen,
            LineStyle = LineStyle.Dash,
            StrokeThickness = 2
        };
        obsLine.Points.Add(new DataPoint(1, obs));
        obsLine.Points.Add(new DataPoint(14, obs));
        model.Series.Add(obsLine);

        return model;
    }

    private PlotModel BuildForecastErrorModel(List<ForecastPoint> data, int year, int month)
    {
        var model = CreateBaseModel(
            $"Abweichung vom eingetroffenen Wert ({new DateTime(year, month, 1):MMMM yyyy})",
            "Fehler (°C)");

        var farben = GetModelColors();

        var modelle = data.Select(e => e.Modell).Distinct().OrderBy(x => x);

        foreach (var modell in modelle)
        {
            var serie = CreateLineSeries(modell, farben);

            var grouped = data
                .Where(e => e.Modell == modell)
                .OrderBy(e => e.VorhersageTag);

            foreach (var g in grouped)
                serie.Points.Add(new DataPoint(g.VorhersageTag, g.Fehler));

            if (serie.Points.Count > 0)
                model.Series.Add(serie);
        }

        var zero = new LineSeries
        {
            Title = "Eingetroffen",
            Color = OxyColors.ForestGreen,
            LineStyle = LineStyle.Dash,
            StrokeThickness = 2
        };
        zero.Points.Add(new DataPoint(1, 0));
        zero.Points.Add(new DataPoint(14, 0));
        model.Series.Add(zero);

        return model;
    }

    private PlotModel CreateBaseModel(string title, string yTitle)
    {
        var model = new PlotModel
        {
            Title = title,
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent
        };

        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Bottom,
            Minimum = 1,
            Maximum = 14,
            MajorStep = 1,
            Title = "Vorhersagetag",
            FontSize = 18
        });

        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Left,
            Title = yTitle,
            FontSize = 18
        });

        model.Legends.Add(new Legend
        {
            LegendPlacement = LegendPlacement.Inside,
            LegendPosition = LegendPosition.BottomRight,
            LegendOrientation = LegendOrientation.Vertical
        });

        return model;
    }

    private LineSeries CreateLineSeries(string modell, Dictionary<string, OxyColor> farben)
    {
        return new LineSeries
        {
            Title = modell,
            Color = farben.ContainsKey(modell) ? farben[modell] : OxyColors.Black,
            StrokeThickness = 1.5,
            MarkerType = MarkerType.Circle,
            MarkerSize = 3.5
        };
    }

    private Dictionary<string, OxyColor> GetModelColors() =>
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["MOSMIX"] = ModelColors.Mosmix,
            ["ICON"] = ModelColors.Icon,
            ["GFS"] = ModelColors.Gfs,
            ["IFS"] = ModelColors.Ifs,
            ["UKMO"] = ModelColors.UKMO,
            ["AIFS"] = OxyColors.MediumPurple,
            ["GEM"] = OxyColors.DarkCyan
        };

    private void ExportPlot(PlotModel model, string path)
    {
        using var stream = File.Create(path);
        new PngExporter { Width = 1150, Height = 640, Dpi = 96 }.Export(model, stream);
    }
}
