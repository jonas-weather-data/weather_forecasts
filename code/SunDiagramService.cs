using OxyPlot;
using OxyPlot.Annotations;
using OxyPlot.Axes;
using OxyPlot.Legends;
using OxyPlot.Series;
using OxyPlot.SkiaSharp;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;

public class SunDiagramService
{
    private readonly string _run;

    public SunDiagramService(string run)
    {
        _run = run;
    }

    public class Sunshine00zData
    {
        public string Date { get; set; } = "";
        public double? MOSMIX { get; set; }
    }

    private double? Load00zSunshineFromJson(DateTime today)
    {
        if (_run == "00z")
            return null;

        const string fileName = "00z_prognose_sun.json";

        if (!File.Exists(fileName))
            return null;

        try
        {
            var data = JsonSerializer.Deserialize<Sunshine00zData>(
            File.ReadAllText(fileName));

            if (data == null)
                return null;

            if (!DateTime.TryParse(data.Date, out var fileDate))
                return null;

            if (fileDate.Date != today.Date)
                return null;

            return data.MOSMIX;
        }
        catch
        {
            return null;
        }
    }

    public string CreateSunDiagram(MosmixData mos, DateTime today)
    {
        double? dbValue = Load00zSunshineFromJson(today);
        if (dbValue.HasValue)
            mos.DailySunMean[today] = dbValue.Value;

        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;
        int daysInMonth = DateTime.DaysInMonth(year, month);

        double[] observedSun = mos.ObservedSun;
        double[] climateSun = mos.ClimateSun;

        int lastObservedDaySun = Math.Min(todayDay - 1, observedSun.Length);
        if (lastObservedDaySun < 1 && observedSun.Length > 0)
            lastObservedDaySun = 1;

        var observedSunUntilObs = observedSun.Take(lastObservedDaySun).ToArray();
        double[] daysObservedSun = Enumerable.Range(1, observedSunUntilObs.Length).Select(i => (double)i).ToArray();

        double startCumSun = observedSunUntilObs.Length > 0 ? observedSunUntilObs.Last() : 0.0;

        int mosmixLastDay = mos.DailySunMean
            .Where(kv => kv.Key.Year == year && kv.Key.Month == month)
            .Select(kv => kv.Key.Day)
            .DefaultIfEmpty(todayDay)
            .Max();

        int? firstForecastDay = mos.DailySunMean
            .Where(kv => kv.Key.Year == year && kv.Key.Month == month && kv.Key.Day >= todayDay)
            .Select(kv => (int?)kv.Key.Day)
            .OrderBy(d => d)
            .FirstOrDefault();

        double endObs = observedSunUntilObs.Length > 0 ? observedSunUntilObs.Last() : 0.0;

        double climObs = climateSun[Math.Max(0, (int)daysObservedSun.LastOrDefault() - 1)];
        double climMos = climateSun[Math.Max(0, mosmixLastDay - 1)];

        string Pct(double value, double clim)
        {
            if (clim <= 0) return "0.0%";
            double pct = value / clim * 100.0;
            return $"{pct:0.0}%";
        }

        var model = new PlotModel
        {
            Title = $"Sonnenschein {today:MMMM yyyy}",
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent,
            Padding = new OxyThickness(10, 10, 10, 10)
        };

        double climEnd = climateSun[daysInMonth - 1];

        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Bottom,
            Minimum = 0.5,
            Maximum = daysInMonth + 0.5,
            Title = "Tag",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.None,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            MinimumPadding = 0.05,
            MaximumPadding = 0.05,
            MajorStep = 1
        });

        model.Axes.Add(new LinearAxis
        {
            Position = AxisPosition.Left,
            Title = "h",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            Minimum = 0,
            Maximum = Math.Max(200, Math.Ceiling(climEnd * 1.05)),
            MinimumPadding = 0.05,
            MaximumPadding = 0.05
        });

        LineSeries Make(string title, OxyColor color, bool withMarkers = true) =>
            new LineSeries
            {
                Title = title,
                Color = color,
                StrokeThickness = 1.5,
                MarkerType = withMarkers ? MarkerType.Circle : MarkerType.None,
                MarkerSize = withMarkers ? 3.5 : 0,
                EdgeRenderingMode = EdgeRenderingMode.PreferSharpness
            };

        var climSeries = Make("Klimamittel 1991–2020", ModelColors.Climate);
        for (int i = 0; i < climateSun.Length; i++)
            climSeries.Points.Add(new DataPoint(i + 1, climateSun[i]));
        model.Series.Add(climSeries);

        if (observedSunUntilObs.Length > 0)
        {
            var obs = Make($"OBS={endObs:F1} ({Pct(endObs, climObs)})", ModelColors.Obs);
            for (int i = 0; i < observedSunUntilObs.Length; i++)
                obs.Points.Add(new DataPoint(i + 1, observedSunUntilObs[i]));
            model.Series.Add(obs);
        }

        double endMos = endObs;

        if (firstForecastDay.HasValue && firstForecastDay.Value <= mosmixLastDay)
        {
            int ff = firstForecastDay.Value;

            double cumMos = startCumSun;

            for (int d = todayDay; d <= ff; d++)
            {
                var date = new DateTime(year, month, d);
                if (mos.DailySunMean.TryGetValue(date, out double val))
                    cumMos += val;
            }

            var mosConnect = Make("", ModelColors.Mosmix, withMarkers: false);
            mosConnect.Points.Add(new DataPoint(lastObservedDaySun, startCumSun));
            mosConnect.Points.Add(new DataPoint(ff, cumMos));
            model.Series.Add(mosConnect);

            var mosS = Make("", ModelColors.Mosmix, withMarkers: true);
            mosS.Points.Add(new DataPoint(ff, cumMos));

            double running = cumMos;
            for (int d = ff + 1; d <= mosmixLastDay; d++)
            {
                var date = new DateTime(year, month, d);
                if (mos.DailySunMean.TryGetValue(date, out double val))
                    running += val;

                mosS.Points.Add(new DataPoint(d, running));
                endMos = running;
            }

            endMos = Math.Max(endMos, cumMos);
            mosS.Title = $"MOSMIX={endMos:F1} ({Pct(endMos, climMos)})";

            model.Series.Add(mosS);
        }

        var legend = new Legend
        {
            LegendPlacement = LegendPlacement.Inside,
            LegendPosition = LegendPosition.BottomRight,
            LegendOrientation = LegendOrientation.Vertical,
            Font = "Segoe UI Bold",
            FontSize = 64,
            LegendSymbolLength = 80,
            LegendItemSpacing = 160,
            LegendPadding = 20,
            LegendBackground = OxyColor.FromAColor(220, OxyColors.White),
            LegendBorder = OxyColors.Gray,
            LegendBorderThickness = 1.5
        };

        model.Legends.Add(legend);

        // Zeitstempel hinzufügen
        var tz = TimeZoneInfo.FindSystemTimeZoneById("Europe/Berlin");
        var nowBerlin = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tz);

        var zone = tz.IsDaylightSavingTime(nowBerlin)
        ? "MESZ"
        : "MEZ";

        var timestamp = nowBerlin.ToString("dd.MM.yyyy, HH:mm") + $" {zone}";
        model.Annotations.Add(new TextAnnotation
        {
            Text = $"Erstellt am {timestamp}",
            TextPosition = new DataPoint((daysInMonth + 1) / 2.0, 0.5),
            Font = "Segoe UI",
            FontSize = 16,
            TextColor = OxyColors.Black,
            StrokeThickness = 0,
            Background = OxyColor.FromAColor(0, OxyColors.White),
            TextHorizontalAlignment = HorizontalAlignment.Right,
            TextVerticalAlignment = VerticalAlignment.Bottom
        });


        string localPath = "sonne_monat.png";

        using (var stream = File.Create(localPath))
        {
            var exporter = new PngExporter
            {
                Width = 1150,
                Height = 640,
                Dpi = 96
            };
            exporter.Export(model, stream);
        }

        var uploader = new GitHubUploader("jonas-weather-data", "weather_forecasts");
        string dateFolder = today.ToString("yyyy-MM-dd");

        uploader.UploadLatestAsync(localPath, "sonne_monat_test.png").GetAwaiter().GetResult();
        uploader.UploadRunLatestAsync(_run, localPath, "sonne_monat_test.png").GetAwaiter().GetResult();

        string link = uploader.UploadRunDayAsync(_run, dateFolder, localPath, "sonne_monat_test.png")
            .GetAwaiter()
            .GetResult();

        return link;
    }
}
