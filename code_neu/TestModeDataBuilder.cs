using System;
using System.Collections.Generic;

public class TestModeDataBuilder
{
    // Auswertestand: 15. Juni 2026
    public DateTime Today => new DateTime(2026, 6, 15);

    public MosmixData BuildMosmixData()
    {
        var today = Today;
        int year = today.Year;
        int month = today.Month;

        var observedTemp = new double[]
        {
            16.85, 17.28, 16.663333, 16.425, 15.996,
            16.015, 16.031428, 16.23375, 16.069, 15.715,
            15.4072, 15.2825, 15.39, 15.3043, 15.196
        };

        var observedRain = new double[] { 0.24, 6.80, 8.64, 14.20 };
        var observedSun = new double[] { 7.82, 14.84, 19.20, 22.20 };

        var climateTemp = new double[]
        {
            14.8, 15.3, 15.4, 15.4, 15.5, 15.6, 15.7, 15.8, 15.9, 16.0,
            16.0, 16.0, 16.0, 16.0, 16.1, 16.1, 16.2, 16.3, 16.3, 16.4,
            16.4, 16.4, 16.4, 16.4, 16.4, 16.5, 16.5, 16.6, 16.6, 16.7
        };

        var climateRain = new double[]
        {
            2.1, 5.2, 8.5, 10.9, 13.6, 16.3, 18.8, 21.6, 23.8, 26.9,
            29.5, 32.2, 34.7, 36.8, 39.6, 42.0, 44.8, 46.9, 49.0, 52.0,
            54.8, 57.7, 60.0, 61.8, 64.4, 65.6, 68.3, 70.3, 73.3, 75.5
        };

        var climateSun = new double[]
        {
            7.3, 14.9, 21.9, 28.9, 36.7, 43.8, 51.4, 59.2, 66.8, 74.0,
            80.4, 86.9, 93.5, 100.2, 107.0, 113.4, 121.2, 128.4, 135.3,
            142.4, 149.0, 155.9, 163.3, 170.8, 177.5, 185.3, 192.8, 200.4, 208.1, 216.0
        };

        var dailyTempMean = new Dictionary<DateTime, double>();
        var dailyRainMean = new Dictionary<DateTime, double>();
        var dailySunMean = new Dictionary<DateTime, double>();

        double[] mosmixTemp =
        {
            15.90, 15.61, 15.37, 15.73, 15.54,
            15.24, 15.28, 15.24, 15.27, 15.26
        };

        double[] mosmixRain = { 1.2, 0.8, 2.0, 0.5, 3.0, 1.0, 0.0, 2.5, 1.5, 0.7 };
        double[] mosmixSun = { 7.0, 8.2, 6.5, 9.0, 8.8, 7.5, 10.0, 9.2, 8.0, 7.8 };

        for (int i = 0; i < mosmixTemp.Length; i++)
        {
            int day = 5 + i; // 5.–14. Juni
            var d = new DateTime(year, month, day);

            dailyTempMean[d] = mosmixTemp[i];
            dailyRainMean[d] = mosmixRain[i];
            dailySunMean[d] = mosmixSun[i];
        }

        return new MosmixData
        {
            DailyTempMean = dailyTempMean,
            DailyRainMean = dailyRainMean,
            DailySunMean = dailySunMean,
            ObservedTemp = observedTemp,
            ObservedRain = observedRain,
            ObservedSun = observedSun,
            ClimateTemp = climateTemp,
            ClimateRain = climateRain,
            ClimateSun = climateSun,
            Top10 = new Dictionary<DateTime, List<(string Station, double Tmax)>>()
        };
    }

    public (Dictionary<string, Dictionary<DateTime, (double val, int count)>> temp,
             Dictionary<string, Dictionary<DateTime, (double val, int count)>> rain,
             Dictionary<string, Dictionary<DateTime, (double val, int count)>> sun)
    BuildModelData()
    {
        var today = Today;
        int year = today.Year;
        int month = today.Month;

        var b = new TestModeForecastBuilder();

        var temp = new Dictionary<string, Dictionary<DateTime, (double, int)>>();

        temp["GFS"] = b.BuildHardcodedModel(
            year, month, 1, 14,
            new double[]
            {
                15.42 * 24, 15.81 * 24, 16.30 * 24, 16.18 * 24,
                14.40 * 24, 13.97 * 24, 14.98 * 24, 15.13 * 24,
                15.12 * 24, 15.11 * 24, 15.08 * 24, 15.00 * 24,
                15.08 * 24, 15.15 * 24
            });

        temp["IFS"] = b.BuildHardcodedModel(
            year, month, 5, 14,
            new double[]
            {
                16.26 * 24, 14.94 * 24, 15.54 * 24, 15.76 * 24,
                15.14 * 24, 14.89 * 24, 15.03 * 24, 15.10 * 24,
                15.15 * 24, 15.20 * 24
            });

        temp["MOSMIX"] = b.BuildHardcodedModel(
            year, month, 5, 14,
            new double[]
            {
                15.90 * 24, 15.61 * 24, 15.37 * 24, 15.73 * 24,
                15.54 * 24, 15.24 * 24, 15.28 * 24, 15.24 * 24,
                15.27 * 24, 15.26 * 24
            });

        temp["ICON"] = b.BuildHardcodedModel(
            year, month, 9, 14,
            new double[]
            {
                15.58 * 24, 15.29 * 24, 15.16 * 24,
                15.09 * 24, 15.20 * 24, 15.23 * 24
            });

        temp["UKMO"] = b.BuildHardcodedModel(
            year, month, 10, 14,
            new double[]
            {
                15.19 * 24, 15.17 * 24, 15.10 * 24,
                15.21 * 24, 15.19 * 24
            });

        temp["AIFS"] = b.BuildHardcodedModel(
            year, month, 14, 14,
            new double[]
            {
                15.29 * 24
            });

        temp["GEM"] = b.BuildHardcodedModel(
            year, month, 14, 14,
            new double[]
            {
                15.32 * 24
            });

        var rain = new Dictionary<string, Dictionary<DateTime, (double, int)>>();

        rain["ICON"] = b.BuildHardcodedModel(year, month, 1, 8,
            new double[] { 4.8, 0, 19.2, 2.4, 0, 28.8, 7.2, 0 });

        rain["GFS"] = b.BuildHardcodedModel(year, month, 1, 16,
            new double[]
            {
                43.2, 21.6, 62.4, 26.4, 76.8, 16.8, 57.6, 38.4,
                24, 72, 31.2, 19.2, 52.8, 36, 14.4, 48
            });

        rain["IFS"] = b.BuildHardcodedModel(year, month, 1, 12,
            new double[]
            {
                26.4, 16.8, 33.6, 21.6, 38.4, 19.2,
                28.8, 21.6, 31.2, 16.8, 36, 21.6
            });

        rain["UKMO"] = b.BuildHardcodedModel(year, month, 1, 6,
            new double[] { 21.6, 14.4, 24, 9.6, 28.8, 16.8 });

        var sun = new Dictionary<string, Dictionary<DateTime, (double, int)>>();

        sun["ICON"] = b.BuildHardcodedModel(year, month, 1, 8,
            new double[] { 120, 140, 160, 150, 130, 170, 180, 160 });

        sun["GFS"] = b.BuildHardcodedModel(year, month, 1, 16,
            new double[]
            {
                100, 120, 140, 160, 180, 200, 220, 210,
                190, 170, 160, 150, 140, 130, 120, 110
            });

        sun["IFS"] = b.BuildHardcodedModel(year, month, 1, 12,
            new double[]
            {
                110, 130, 150, 160, 170, 180,
                190, 200, 210, 220, 230, 240
            });

        sun["UKMO"] = b.BuildHardcodedModel(year, month, 1, 6,
            new double[] { 90, 110, 130, 150, 170, 160 });

        return (temp, rain, sun);
    }
}
