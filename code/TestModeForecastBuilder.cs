using System;
using System.Collections.Generic;

public class TestModeForecastBuilder
{
    private readonly TestModeForecastRepository _repo = new();

    public void WriteAllTestForecastsToDb(
        DateTime today,
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> temp,
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> rain,
        Dictionary<string, Dictionary<DateTime, (double val, int count)>> sun)
    {
        foreach (var model in temp.Keys)
        {
            var tempDict = temp[model];
            var rainDict = rain.ContainsKey(model) ? rain[model] : null;
            var sunDict = sun.ContainsKey(model) ? sun[model] : null;

            foreach (var kv in tempDict)
            {
                DateTime date = kv.Key;
                var (tempSum, tempCount) = kv.Value;

                decimal? tmk = tempCount > 0
                    ? (decimal?)(tempSum / tempCount)
                    : null;

                decimal? rsk = null;
                if (rainDict != null &&
                    rainDict.TryGetValue(date, out var r) &&
                    r.count > 0)
                {
                    rsk = (decimal?)(r.val / r.count);
                }

                decimal? sdk = null;
                if (sunDict != null &&
                    sunDict.TryGetValue(date, out var s) &&
                    s.count > 0)
                {
                    sdk = (decimal?)(s.val / s.count);
                }

                int vorhersageTag = (date - today.Date).Days;

                _repo.InsertTestForecast(
                    date,
                    model,
                    vorhersageTag,
                    tmk,
                    sdk,
                    rsk
                );
            }
        }
    }

    // Hilfsfunktion für TestmodeService, um Hardcoded-Modelle zu erzeugen
    public Dictionary<DateTime, (double val, int count)> BuildHardcodedModel(
        int year,
        int month,
        int startDay,
        int lastDay,
        double[] sums)
    {
        var dict = new Dictionary<DateTime, (double val, int count)>();
        int len = lastDay - startDay + 1;

        if (sums.Length < len)
            throw new InvalidOperationException("Zu wenige Werte für Modell im Testmodus.");

        for (int d = startDay; d <= lastDay; d++)
        {
            int idx = d - startDay;
            dict[new DateTime(year, month, d)] = (sums[idx], 24);
        }

        return dict;
    }
}
