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

public class RainDiagramService
{
    private readonly string _run;

    public RainDiagramService(string run)
    {
        _run = run;
    }

    public class Rain00zData
    {
        public string Date { get; set; } = "";
        public double? MOSMIX { get; set; }
        public double? ICON { get; set; }
        public double? GFS { get; set; }
        public double? IFS { get; set; }
        public double? AIFS { get; set; }
        public double? UKMO { get; set; }
        public double? GEM { get; set; }
    }

    private double? Load00zRainFromJson(string model, DateTime today)
    {
        if (_run == "00z")
            return null;

        const string fileName = "00z_prognose_rain.json";

        if (!File.Exists(fileName))
            return null;

        try
        {
            var data = JsonSerializer.Deserialize<Rain00zData>(
            File.ReadAllText(fileName));

            if (data == null)
                return null;

            if (!DateTime.TryParse(data.Date, out var fileDate))
                return null;

            if (fileDate.Date != today.Date)
                return null;

            return model switch
            {
                "MOSMIX" => data.MOSMIX,
                "ICON" => data.ICON,
                "GFS" => data.GFS,
                "IFS" => data.IFS,
                "AIFS" => data.AIFS,
                "UKMO" => data.UKMO,
                "GEM" => data.GEM,
                _ => null
            };
        }
        catch
        {
            return null;
        }
    }

    public string CreateRainDiagram(MosmixData mos, OpenMeteoData om, DateTime today)
    {
        double? dbValue = Load00zRainFromJson("MOSMIX", today);
        if (dbValue.HasValue)
            mos.DailyRainMean[today] = dbValue.Value;

        double? icon00 = Load00zRainFromJson("ICON", today);
        double? gfs00 = Load00zRainFromJson("GFS", today);
        double? ifs00 = Load00zRainFromJson("IFS", today);
        double? aifs00 = Load00zRainFromJson("AIFS", today);
        double? ukmo00 = Load00zRainFromJson("UKMO", today);
        double? gem00 = Load00zRainFromJson("GEM", today);

        if (icon00.HasValue) om.Rain["ICON"][today] = (icon00.Value, 1);
        if (gfs00.HasValue) om.Rain["GFS"][today] = (gfs00.Value, 1);
        if (ifs00.HasValue) om.Rain["IFS"][today] = (ifs00.Value, 1);
        if (aifs00.HasValue) om.Rain["AIFS"][today] = (aifs00.Value, 1);
        if (ukmo00.HasValue) om.Rain["UKMO"][today] = (ukmo00.Value, 1);
        if (gem00.HasValue) om.Rain["GEM"][today] = (gem00.Value, 1);

        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;
        int daysInMonth = DateTime.DaysInMonth(year, month);

        double[] observedRain = mos.ObservedRain;
        double[] climateRain = mos.ClimateRain;

        int lastObservedDayRain = Math.Min(todayDay - 1, observedRain.Length);
        if (lastObservedDayRain < 1 && observedRain.Length > 0)
            lastObservedDayRain = 1;

        var observedRainUntilObs = observedRain.Take(lastObservedDayRain).ToArray();
        double[] daysObservedRain = Enumerable.Range(1, observedRainUntilObs.Length).Select(i => (double)i).ToArray();

        double startCumRain = observedRainUntilObs.Length > 0 ? observedRainUntilObs.Last() : 0.0;

        int mosmixLastDay = mos.DailyRainMean
            .Where(kv => kv.Key.Year == year && kv.Key.Month == month)
            .Select(kv => kv.Key.Day)
            .DefaultIfEmpty(todayDay)
            .Max();

        int? firstForecastDay = mos.DailyRainMean
            .Where(kv => kv.Key.Year == year && kv.Key.Month == month && kv.Key.Day >= todayDay)
            .Select(kv => (int?)kv.Key.Day)
            .OrderBy(d => d)
            .FirstOrDefault();

        double endMos = startCumRain;

        int forecastStartDay = todayDay;

        int lastIconDay = GetLastValidRainDay(om.Rain["ICON"], year, month, forecastStartDay);
        int lastGfsDay = GetLastValidRainDay(om.Rain["GFS"], year, month, forecastStartDay);
        int lastIfsDay = GetLastValidRainDay(om.Rain["IFS"], year, month, forecastStartDay);
        int lastAifsDay = GetLastValidRainDay(om.Rain["AIFS"], year, month, forecastStartDay);
        int lastUkmoDay = GetLastValidRainDay(om.Rain["UKMO"], year, month, forecastStartDay);
        int lastGemDay = GetLastValidRainDay(om.Rain["GEM"], year, month, forecastStartDay);

        var iconRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["ICON"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastIconDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        var gfsRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["GFS"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastGfsDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        var ifsRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["IFS"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastIfsDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        var aifsRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["AIFS"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastAifsDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        var ukmoRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["UKMO"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastUkmoDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        var gemRaw = OpenMeteoAggregator.BuildCumulativeSeries(
            om.Rain["GEM"]
                .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Key.Day <= lastGemDay)
                .ToDictionary(k => k.Key, v => (v.Value.rain, v.Value.count)),
            startCumRain);

        double endObs = observedRainUntilObs.Length > 0 ? observedRainUntilObs.Last() : 0.0;
        double endIcon = iconRaw.values.Length > 0 ? iconRaw.values.Last() : endObs;
        double endGfs = gfsRaw.values.Length > 0 ? gfsRaw.values.Last() : endObs;
        double endIfs = ifsRaw.values.Length > 0 ? ifsRaw.values.Last() : endObs;
        double endAifs = aifsRaw.values.Length > 0 ? aifsRaw.values.Last() : endObs;
        double endUkmo = ukmoRaw.values.Length > 0 ? ukmoRaw.values.Last() : endObs;
        double endGem = gemRaw.values.Length > 0 ? gemRaw.values.Last() : endObs;

        double climObs = climateRain[Math.Max(0, lastObservedDayRain - 1)];
        double climMos = climateRain[Math.Max(0, mosmixLastDay - 1)];
        double climIcon = climateRain[Math.Max(0, lastIconDay - 1)];
        double climGfs = climateRain[Math.Max(0, lastGfsDay - 1)];
        double climIfs = climateRain[Math.Max(0, lastIfsDay - 1)];
        double climAifs = climateRain[Math.Max(0, lastAifsDay - 1)];
        double climUkmo = climateRain[Math.Max(0, lastUkmoDay - 1)];
        double climGem = climateRain[Math.Max(0, lastGemDay - 1)];

        string Pct(double value, double clim)
        {
            if (clim <= 0) return "0.0%";
            double pct = value / clim * 100.0;
            return $"{pct:0.0}%";
        }

        var model = new PlotModel
        {
            Title = $"Niederschlag {today:MMMM yyyy}",
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent,
            Padding = new OxyThickness(10, 10, 10, 10)
        };

        double climEnd = climateRain[daysInMonth - 1];

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
            Title = "mm",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            Minimum = 0,
            Maximum = Math.Max(100, Math.Ceiling(climEnd * 1.05)),
            MinimumPadding = 0.05,
            MaximumPadding = 0.05
        });

        LineSeries Make(string title, OxyColor color) =>
            new LineSeries
            {
                Title = title,
                Color = color,
                StrokeThickness = 1.5,
                MarkerType = MarkerType.Circle,
                MarkerSize = 3.5,
                EdgeRenderingMode = EdgeRenderingMode.PreferSharpness
            };

        var climSeries = Make("Klimamittel 1991–2020", ModelColors.Climate);
        for (int i = 0; i < climateRain.Length; i++)
            climSeries.Points.Add(new DataPoint(i + 1, climateRain[i]));
        model.Series.Add(climSeries);

        if (observedRainUntilObs.Length > 0)
        {
            var obs = Make($"OBS={endObs:F1} ({Pct(endObs, climObs)})", ModelColors.Obs);
            for (int i = 0; i < observedRainUntilObs.Length; i++)
                obs.Points.Add(new DataPoint(i + 1, observedRainUntilObs[i]));
            model.Series.Add(obs);
        }

        if (firstForecastDay.HasValue && firstForecastDay.Value <= mosmixLastDay)
        {
            int ff = firstForecastDay.Value;

            double cumMos = startCumRain;
            for (int d = todayDay; d <= ff; d++)
            {
                var date = new DateTime(year, month, d);
                if (mos.DailyRainMean.TryGetValue(date, out double val))
                    cumMos += val;
            }

            var mosConnect = new LineSeries
            {
                Title = "",
                Color = OxyColor.FromRgb(0, 87, 183),
                StrokeThickness = 1.5,
                MarkerType = MarkerType.None
            };
            mosConnect.Points.Add(new DataPoint(lastObservedDayRain, startCumRain));
            mosConnect.Points.Add(new DataPoint(ff, cumMos));
            model.Series.Add(mosConnect);

            var mosS = Make("", OxyColor.FromRgb(0, 87, 183));
            mosS.Points.Add(new DataPoint(ff, cumMos));

            double running = cumMos;
            for (int d = ff + 1; d <= mosmixLastDay; d++)
            {
                var date = new DateTime(year, month, d);
                if (mos.DailyRainMean.TryGetValue(date, out double val))
                    running += val;

                mosS.Points.Add(new DataPoint(d, running));
                endMos = running;
            }

            mosS.Title = $"MOSMIX={endMos:F1} ({Pct(endMos, climMos)})";
            model.Series.Add(mosS);
        }

        Add(model, iconRaw, endIcon, climIcon, "ICON", ModelColors.Icon, lastIconDay);
        Add(model, gfsRaw, endGfs, climGfs, "GFS", ModelColors.Gfs, lastGfsDay);
        Add(model, ifsRaw, endIfs, climIfs, "IFS", ModelColors.Ifs, lastIfsDay);
        Add(model, aifsRaw, endAifs, climAifs, "AIFS", ModelColors.AIFS, lastAifsDay);
        Add(model, ukmoRaw, endUkmo, climUkmo, "UKMO", ModelColors.UKMO, lastUkmoDay);
        Add(model, gemRaw, endGem, climGem, "GEM", ModelColors.GEM, lastGemDay);

        var legend = new Legend
        {
            LegendPlacement = LegendPlacement.Inside,
            LegendPosition = LegendPosition.TopLeft,
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
            // X: Monatsmitte, Y: etwas über Achsenminimum (0)
            TextPosition = new DataPoint((daysInMonth + 1) / 2.0, 2.0),
            Font = "Segoe UI",
            FontSize = 16,
            TextColor = OxyColors.Black,
            StrokeThickness = 0,
            Background = OxyColor.FromAColor(0, OxyColors.White),
            TextHorizontalAlignment = HorizontalAlignment.Center,
            TextVerticalAlignment = VerticalAlignment.Bottom
        });


        string localPath = "regen_monat.png";

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

        uploader.UploadLatestAsync(localPath, "regen_monat_test.png").GetAwaiter().GetResult();
        uploader.UploadRunLatestAsync(_run, localPath, "regen_monat_test.png").GetAwaiter().GetResult();

        string link = uploader.UploadRunDayAsync(_run, dateFolder, localPath, "regen_monat_test.png")
            .GetAwaiter()
            .GetResult();

        return link;
    }

    private static void Add(
        PlotModel model,
        (double[] days, double[] values) raw,
        double endValue,
        double climValue,
        string label,
        OxyColor color,
        int lastDay)
    {
        if (raw.days.Length == 0)
            return;

        string pctText = climValue > 0
            ? $"{(endValue / climValue * 100.0):0.0}%"
            : "0.0%";

        var obsSeries = model.Series
            .OfType<LineSeries>()
            .FirstOrDefault(x => x.Title.StartsWith("OBS"));

        double obsX = obsSeries?.Points.Last().X ?? 3.0;
        double obsY = obsSeries?.Points.Last().Y ?? 0.0;

        double firstModelDay = raw.days[0];
        double firstModelVal = raw.values[0];

        var connect = new LineSeries
        {
            Title = "",
            Color = color,
            StrokeThickness = 1.5,
            MarkerType = MarkerType.None
        };
        connect.Points.Add(new DataPoint(obsX, obsY));
        connect.Points.Add(new DataPoint(firstModelDay, firstModelVal));
        model.Series.Add(connect);

        var s = new LineSeries
        {
            Title = $"{label}={endValue:F1} ({pctText})",
            Color = color,
            StrokeThickness = 1.5,
            MarkerType = MarkerType.Circle,
            MarkerSize = 3.5,
            EdgeRenderingMode = EdgeRenderingMode.PreferSharpness
        };

        for (int i = 0; i < raw.days.Length; i++)
        {
            if (raw.days[i] > lastDay)
                break;

            s.Points.Add(new DataPoint(raw.days[i], raw.values[i]));
        }

        model.Series.Add(s);
    }

    private static int GetLastValidRainDay(
        Dictionary<DateTime, (double rain, int count)> modelData,
        int year,
        int month,
        int forecastStartDay)
    {
        return modelData
            .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Value.count > 0)
            .Select(k => new { Day = k.Key.Day, Mean = k.Value.rain / k.Value.count })
            .Where(x => x.Mean > 0.0)
            .Select(x => x.Day)
            .DefaultIfEmpty(forecastStartDay - 1)
            .Max();
    }
}
