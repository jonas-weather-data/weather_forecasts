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

public class TempDiagramService
{
    private readonly string _run;

    public TempDiagramService(string run)
    {
        _run = run;
    }

    public class Temp00zData
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

    private double? Load00zTempFromJson(string model, DateTime today)
    {
        if (_run == "00z")
            return null;

        const string fileName = "00z_prognose_temp.json";

        if (!File.Exists(fileName))
            return null;

        try
        {
            var data = JsonSerializer.Deserialize<Temp00zData>(
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

    public string CreateTempDiagram(MosmixData mos, OpenMeteoData om, DateTime today)
    {
        double? dbValue = Load00zTempFromJson("MOSMIX", today);
        if (dbValue.HasValue)
            mos.DailyTempMean[today] = dbValue.Value;

        double? icon00 = Load00zTempFromJson("ICON", today);
        double? gfs00 = Load00zTempFromJson("GFS", today);
        double? ifs00 = Load00zTempFromJson("IFS", today);
        double? aifs00 = Load00zTempFromJson("AIFS", today);
        double? ukmo00 = Load00zTempFromJson("UKMO", today);
        double? gem00 = Load00zTempFromJson("GEM", today);

        if (icon00.HasValue) om.Temp["ICON"][today] = (icon00.Value, 1);
        if (gfs00.HasValue) om.Temp["GFS"][today] = (gfs00.Value, 1);
        if (ifs00.HasValue) om.Temp["IFS"][today] = (ifs00.Value, 1);
        if (aifs00.HasValue) om.Temp["AIFS"][today] = (aifs00.Value, 1);
        if (ukmo00.HasValue) om.Temp["UKMO"][today] = (ukmo00.Value, 1);
        if (gem00.HasValue) om.Temp["GEM"][today] = (gem00.Value, 1);

        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;
        int daysInMonth = DateTime.DaysInMonth(year, month);

        double[] observedTemp = mos.ObservedTemp;
        double[] climateTemp = mos.ClimateTemp;

        int lastObservedDayTemp = Math.Min(todayDay - 1, observedTemp.Length);
        if (lastObservedDayTemp < 1 && observedTemp.Length > 0)
            lastObservedDayTemp = 1;

        var observedTempUntilObs = observedTemp.Take(lastObservedDayTemp).ToArray();
        double[] daysObservedTemp = Enumerable.Range(1, observedTempUntilObs.Length).Select(i => (double)i).ToArray();

        double lastObservedTempMean = observedTempUntilObs.Length > 0 ? observedTempUntilObs.Last() : 0.0;
        int forecastStartDay = todayDay;

        int lastIconDayTempRaw = GetLastValidTempDay(om.Temp["ICON"], year, month, forecastStartDay);
        int lastGfsDayTempRaw = GetLastValidTempDay(om.Temp["GFS"], year, month, forecastStartDay);
        int lastIfsDayTempRaw = GetLastValidTempDay(om.Temp["IFS"], year, month, forecastStartDay);
        int lastAifsDayTempRaw = GetLastValidTempDay(om.Temp["AIFS"], year, month, forecastStartDay);
        int lastUkmoDayTempRaw = GetLastValidTempDay(om.Temp["UKMO"], year, month, forecastStartDay);
        int lastGemDayTempRaw = GetLastValidTempDay(om.Temp["GEM"], year, month, forecastStartDay);

        var helper = new OpenMeteoService(null, null);

        var iconSeries = helper.BuildTempSeries(om.Temp["ICON"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastIconDayTempRaw, year, month, "ICON");
        var gfsSeries = helper.BuildTempSeries(om.Temp["GFS"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastGfsDayTempRaw, year, month, "GFS");
        var ifsSeries = helper.BuildTempSeries(om.Temp["IFS"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastIfsDayTempRaw, year, month, "IFS");
        var aifsSeries = helper.BuildTempSeries(om.Temp["AIFS"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastAifsDayTempRaw, year, month, "AIFS");
        var ukmoSeries = helper.BuildTempSeries(om.Temp["UKMO"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastUkmoDayTempRaw, year, month, "UKMO");
        var gemSeries = helper.BuildTempSeries(om.Temp["GEM"], lastObservedDayTemp, lastObservedTempMean, forecastStartDay, lastGemDayTempRaw, year, month, "GEM");

        int lastIconDayDataTemp = iconSeries.days.Count > 0 ? iconSeries.days.Last() : lastObservedDayTemp;
        int lastGfsDayDataTemp = gfsSeries.days.Count > 0 ? gfsSeries.days.Last() : lastObservedDayTemp;
        int lastIfsDayDataTemp = ifsSeries.days.Count > 0 ? ifsSeries.days.Last() : lastObservedDayTemp;
        int lastAifsDayDataTemp = aifsSeries.days.Count > 0 ? aifsSeries.days.Last() : lastObservedDayTemp;
        int lastUkmoDayDataTemp = ukmoSeries.days.Count > 0 ? ukmoSeries.days.Last() : lastObservedDayTemp;
        int lastGemDayDataTemp = gemSeries.days.Count > 0 ? gemSeries.days.Last() : lastObservedDayTemp;

        var mosmixTempDays = new List<int>();
        var mosmixTempCum = new List<double>();

        int nMos = lastObservedDayTemp;
        double sumMos = lastObservedTempMean * lastObservedDayTemp;

        if (lastObservedDayTemp > 0)
        {
            mosmixTempDays.Add(lastObservedDayTemp);
            mosmixTempCum.Add(lastObservedTempMean);
        }

        foreach (var kv in mos.DailyTempMean.OrderBy(k => k.Key))
        {
            if (kv.Key.Year != year || kv.Key.Month != month)
                continue;

            int d = kv.Key.Day;
            if (d < forecastStartDay || d > daysInMonth)
                continue;

            double dayMean = kv.Value;
            nMos++;
            sumMos += dayMean;
            double cumMean = sumMos / nMos;

            mosmixTempDays.Add(d);
            mosmixTempCum.Add(cumMean);
        }

        double endObsTemp = observedTempUntilObs.Length > 0 ? observedTempUntilObs.Last() : 0.0;
        double endMosTemp = mosmixTempCum.Count > 0 ? mosmixTempCum.Last() : endObsTemp;
        double endIconTemp = iconSeries.cumMeans.Count > 0 ? iconSeries.cumMeans.Last() : endObsTemp;
        double endGfsTemp = gfsSeries.cumMeans.Count > 0 ? gfsSeries.cumMeans.Last() : endObsTemp;
        double endIfsTemp = ifsSeries.cumMeans.Count > 0 ? ifsSeries.cumMeans.Last() : endObsTemp;
        double endAifsTemp = aifsSeries.cumMeans.Count > 0 ? aifsSeries.cumMeans.Last() : endObsTemp;
        double endUkmoTemp = ukmoSeries.cumMeans.Count > 0 ? ukmoSeries.cumMeans.Last() : endObsTemp;
        double endGemTemp = gemSeries.cumMeans.Count > 0 ? gemSeries.cumMeans.Last() : endObsTemp;

        double climObsTemp = climateTemp[Math.Max(0, (int)daysObservedTemp.LastOrDefault() - 1)];
        double climMosTemp = climateTemp[Math.Max(0, mosmixTempDays.LastOrDefault() - 1)];
        double climIconTemp = climateTemp[Math.Max(0, lastIconDayDataTemp - 1)];
        double climGfsTemp = climateTemp[Math.Max(0, lastGfsDayDataTemp - 1)];
        double climIfsTemp = climateTemp[Math.Max(0, lastIfsDayDataTemp - 1)];
        double climAifsTemp = climateTemp[Math.Max(0, lastAifsDayDataTemp - 1)];
        double climUkmoTemp = climateTemp[Math.Max(0, lastUkmoDayDataTemp - 1)];
        double climGemTemp = climateTemp[Math.Max(0, lastGemDayDataTemp - 1)];

        string Diff(double value, double clim)
        {
            double d = value - clim;
            return d >= 0 ? $"+{d:F2}" : $"{d:F2}";
        }

        var model = new PlotModel
        {
            Title = $"Fortlaufendes Temperaturmittel {today:MMMM yyyy}",
            TitleFont = "Segoe UI Semibold",
            TitleFontSize = 24,
            Background = OxyColors.White,
            TextColor = OxyColors.Black,
            PlotAreaBorderColor = OxyColors.Transparent,
            Padding = new OxyThickness(10, 10, 10, 10)
        };

        double minTemp = new[] {
            observedTempUntilObs.Length > 0 ? observedTempUntilObs.Min() : double.MaxValue,
            climateTemp.Min(),
            iconSeries.cumMeans.Count > 0 ? iconSeries.cumMeans.Min() : double.MaxValue,
            gfsSeries.cumMeans.Count > 0 ? gfsSeries.cumMeans.Min() : double.MaxValue,
            ifsSeries.cumMeans.Count > 0 ? ifsSeries.cumMeans.Min() : double.MaxValue,
            aifsSeries.cumMeans.Count > 0 ? aifsSeries.cumMeans.Min() : double.MaxValue,
            ukmoSeries.cumMeans.Count > 0 ? ukmoSeries.cumMeans.Min() : double.MaxValue,
            gemSeries.cumMeans.Count > 0 ? gemSeries.cumMeans.Min() : double.MaxValue
        }.Min();
        
                double maxTemp = new[] {
            observedTempUntilObs.Length > 0 ? observedTempUntilObs.Max() : double.MinValue,
            climateTemp.Max(),
            iconSeries.cumMeans.Count > 0 ? iconSeries.cumMeans.Max() : double.MinValue,
            gfsSeries.cumMeans.Count > 0 ? gfsSeries.cumMeans.Max() : double.MinValue,
            ifsSeries.cumMeans.Count > 0 ? ifsSeries.cumMeans.Max() : double.MinValue,
            aifsSeries.cumMeans.Count > 0 ? aifsSeries.cumMeans.Max() : double.MinValue,
            ukmoSeries.cumMeans.Count > 0 ? ukmoSeries.cumMeans.Max() : double.MinValue,
            gemSeries.cumMeans.Count > 0 ? gemSeries.cumMeans.Max() : double.MinValue
        }.Max();


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
            Title = "°C",
            TitleFont = "Segoe UI Bold",
            TitleFontSize = 26,
            FontSize = 22,
            MajorGridlineStyle = LineStyle.Solid,
            MinorGridlineStyle = LineStyle.Dot,
            MajorGridlineColor = OxyColor.FromRgb(120, 120, 120),
            MinorGridlineColor = OxyColor.FromRgb(150, 150, 150),
            Minimum = Math.Floor(minTemp) - 1,
            Maximum = Math.Ceiling(maxTemp) + 1,
            MinimumPadding = 0.05,
            MaximumPadding = 0.05
        });

        LineSeries MakeSeries(string title, OxyColor color) =>
            new LineSeries
            {
                Title = title,
                Color = color,
                StrokeThickness = 1.5,
                MarkerType = MarkerType.Circle,
                MarkerSize = 3.5,
                EdgeRenderingMode = EdgeRenderingMode.PreferSharpness
            };

        var climateSeries = MakeSeries("Klimamittel 1991–2020", ModelColors.Climate);
        for (int i = 0; i < climateTemp.Length; i++)
            climateSeries.Points.Add(new DataPoint(i + 1, climateTemp[i]));
        model.Series.Add(climateSeries);

        if (mosmixTempDays.Count > 1)
        {
            var mosSeries = MakeSeries($"MOSMIX={endMosTemp:F2} ({Diff(endMosTemp, climMosTemp)})", ModelColors.Mosmix);
            for (int i = 0; i < mosmixTempDays.Count; i++)
                mosSeries.Points.Add(new DataPoint(mosmixTempDays[i], mosmixTempCum[i]));
            model.Series.Add(mosSeries);
        }

        AddForecastSeries(model, iconSeries, endIconTemp, climIconTemp, "ICON", ModelColors.Icon, Diff);
        AddForecastSeries(model, gfsSeries, endGfsTemp, climGfsTemp, "GFS", ModelColors.Gfs, Diff);
        AddForecastSeries(model, ifsSeries, endIfsTemp, climIfsTemp, "IFS", ModelColors.Ifs, Diff);
        AddForecastSeries(model, aifsSeries, endAifsTemp, climAifsTemp, "AIFS", ModelColors.AIFS, Diff);
        AddForecastSeries(model, ukmoSeries, endUkmoTemp, climUkmoTemp, "UKMO", ModelColors.UKMO, Diff);
        AddForecastSeries(model, gemSeries, endGemTemp, climGemTemp, "GEM", ModelColors.GEM, Diff);

        if (observedTempUntilObs.Length > 0)
        {
            var obsSeries = MakeSeries($"OBS={endObsTemp:F2} ({Diff(endObsTemp, climObsTemp)})", ModelColors.Obs);
            for (int i = 0; i < observedTempUntilObs.Length; i++)
                obsSeries.Points.Add(new DataPoint(i + 1, observedTempUntilObs[i]));
            model.Series.Add(obsSeries);
        }

        var legend = new Legend
        {
            LegendPlacement = LegendPlacement.Inside,
            LegendPosition = LegendPosition.BottomLeft,
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
        var timestamp = DateTime.Now.ToString("dd.MM.yyyy, HH:mm 'MESZ'");
        model.Annotations.Add(new TextAnnotation
        {
            Text = $"Erstellt am {timestamp}",
            TextPosition = new DataPoint((daysInMonth + 1) / 2.0, minTemp - 1),
            Font = "Segoe UI",
            FontSize = 16,
            TextColor = OxyColors.Black,
            StrokeThickness = 0,
            Background = OxyColor.FromAColor(0, OxyColors.White),
            TextHorizontalAlignment = HorizontalAlignment.Center,
            TextVerticalAlignment = VerticalAlignment.Bottom
        });

        string localPath = "temperatur_monat.png";

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

        uploader.UploadLatestAsync(localPath, "temperatur_monat_test.png").GetAwaiter().GetResult();
        uploader.UploadRunLatestAsync(_run, localPath, "temperatur_monat_test.png").GetAwaiter().GetResult();

        string link = uploader.UploadRunDayAsync(_run, dateFolder, localPath, "temperatur_monat_test.png")
            .GetAwaiter()
            .GetResult();

        return link;
    }

    private static void AddForecastSeries(
        PlotModel model,
        (List<int> days, List<double> cumMeans, Dictionary<int, double> dayMeans) series,
        double endValue,
        double climValue,
        string labelPrefix,
        OxyColor color,
        Func<double, double, string> diffFormatter)
    {
        if (series.days.Count <= 1)
            return;

        var s = new LineSeries
        {
            Title = $"{labelPrefix}={endValue:F2} ({diffFormatter(endValue, climValue)})",
            Color = color,
            StrokeThickness = 1.5,
            MarkerType = MarkerType.Circle,
            MarkerSize = 3.5
        };

        for (int i = 0; i < series.days.Count; i++)
            s.Points.Add(new DataPoint(series.days[i], series.cumMeans[i]));

        model.Series.Add(s);
    }

    private static int GetLastValidTempDay(
        Dictionary<DateTime, (double temp, int count)> modelData,
        int year,
        int month,
        int forecastStartDay)
    {
        return modelData
            .Where(k => k.Key.Year == year && k.Key.Month == month && k.Key.Day >= forecastStartDay && k.Value.count > 0)
            .Select(k => new { Day = k.Key.Day, Mean = k.Value.temp / k.Value.count })
            .Where(x => x.Mean > 0.0)
            .Select(x => x.Day)
            .DefaultIfEmpty(forecastStartDay - 1)
            .Max();
    }
}
