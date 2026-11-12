using OxyPlot;
using OxyPlot.Axes;
using OxyPlot.Series;
using OxyPlot.Legends;
using OxyPlot.SkiaSharp;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

public class SunBundeslandDiagramService
{
    public void Create(Dictionary<string, List<(DateTime date, double daily, double cum)>> series)
    {
        var allDates = series.Values.SelectMany(v => v.Select(x => x.date)).Distinct().OrderBy(d => d).ToList();
        if (allDates.Count == 0) return;

        DateTime startDate = allDates.First();
        DateTime endDate = allDates.Last();

        var model = new PlotModel
        {
            Title = $"Fortlaufende Sonnenscheindauer – Bundesländer {startDate:dd.MM} – {endDate:dd.MM}",
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent,
            Padding = new OxyThickness(10, 10, 140, 10) // Platz für Legende rechts
        };

        var dateAxis = new DateTimeAxis
        {
            Position = AxisPosition.Bottom,
            Title = "Tag",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            StringFormat = "dd.MM",
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            Minimum = DateTimeAxis.ToDouble(startDate.AddDays(-0.5)),
            Maximum = DateTimeAxis.ToDouble(endDate.AddDays(0.5)),
            IntervalType = DateTimeIntervalType.Days,
            MinorIntervalType = DateTimeIntervalType.Days,
            MajorStep = 1,
            MinimumPadding = 0.05,
            MaximumPadding = 0.05
        };
        model.Axes.Add(dateAxis);

        double minVal = series.Values.SelectMany(v => v.Select(x => x.cum)).DefaultIfEmpty(0).Min();
        double maxVal = series.Values.SelectMany(v => v.Select(x => x.cum)).DefaultIfEmpty(0).Max();

        var valueAxis = new LinearAxis
        {
            Position = AxisPosition.Left,
            Title = "Stunden",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            Minimum = Math.Floor(minVal - 1.0),
            Maximum = Math.Ceiling(maxVal + 1.0),
            MinimumPadding = 0.05,
            MaximumPadding = 0.05
        };
        model.Axes.Add(valueAxis);

        var shortNames = new Dictionary<string, string>
        {
            ["Baden-Württemberg"] = "BW",
            ["Bayern"] = "BY",
            ["Berlin"] = "BE",
            ["Brandenburg"] = "BB",
            ["Bremen"] = "HB",
            ["Hamburg"] = "HH",
            ["Hessen"] = "HE",
            ["Mecklenburg-Vorpommern"] = "MV",
            ["Niedersachsen"] = "NI",
            ["Nordrhein-Westfalen"] = "NW",
            ["Rheinland-Pfalz"] = "RP",
            ["Saarland"] = "SL",
            ["Sachsen"] = "SN",
            ["Sachsen-Anhalt"] = "ST",
            ["Schleswig-Holstein"] = "SH",
            ["Thüringen"] = "TH"
        };

        var palette = new[]
        {
            OxyColors.Goldenrod, OxyColors.DarkOrange, OxyColors.Olive, OxyColors.SaddleBrown,
            OxyColors.DarkKhaki, OxyColors.Peru, OxyColors.Chocolate, OxyColors.Tan,
            OxyColors.DarkGoldenrod, OxyColors.Brown, OxyColors.Coral, OxyColors.DarkRed,
            OxyColors.OrangeRed, OxyColors.Firebrick, OxyColors.Maroon, OxyColors.Sienna
        };

        int colorIndex = 0;

        foreach (var kv in series.OrderBy(k => k.Key))
        {
            string bl = kv.Key;
            var values = kv.Value;
            if (values.Count == 0) continue;

            double endCum = values[^1].cum;

            var ls = new LineSeries
            {
                Title = $"{shortNames.GetValueOrDefault(bl, bl)} = {endCum:F1}",
                Color = palette[colorIndex % palette.Length],
                StrokeThickness = 1.5,
                MarkerType = MarkerType.Circle,
                MarkerSize = 3.5,
                EdgeRenderingMode = EdgeRenderingMode.PreferSharpness
            };

            foreach (var v in values)
                ls.Points.Add(DateTimeAxis.CreateDataPoint(v.date, v.cum));

            model.Series.Add(ls);
            colorIndex++;
        }

        var legend = new Legend
        {
            LegendPlacement = LegendPlacement.Outside,
            LegendPosition = LegendPosition.RightTop,
            LegendOrientation = LegendOrientation.Vertical,
            Font = "Segoe UI Bold",
            FontSize = 18,
            LegendSymbolLength = 40,
            LegendItemSpacing = 10,
            LegendPadding = 10,
            LegendBackground = OxyColor.FromAColor(220, OxyColors.White),
            LegendBorder = OxyColors.Gray,
            LegendBorderThickness = 1.5
        };
        model.Legends.Add(legend);

        Directory.CreateDirectory("output/diagramme/bundesland/sun");

        using var stream = File.Create("output/diagramme/bundesland/sun/bundeslaender_sonne.png");
        var exporter = new PngExporter
        {
            Width = 1150,
            Height = 640,
            Dpi = 96
        };
        exporter.Export(model, stream);
    }
}
