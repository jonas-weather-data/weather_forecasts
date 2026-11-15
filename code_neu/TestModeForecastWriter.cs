using System;
using System.Collections.Generic;

public class TestModeForecastWriter
{
    private readonly TestModeForecastRepository _repo = new();

    public void WriteForecasts(
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

            int lastDay = tempDict.Keys.Max(d => d.Day);
            int firstDay = tempDict.Keys.Min(d => d.Day);

            foreach (var kv in tempDict)
            {
                DateTime date = kv.Key;
                var (tempSum, tempCount) = kv.Value;

                decimal? tmk = tempCount > 0 ? (decimal?)(tempSum / tempCount) : null;

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

                int vorhersageTag;

                if (model.Equals("MOSMIX", StringComparison.OrdinalIgnoreCase))
                {
                    vorhersageTag = (date.Day - firstDay) + 1;
                }
                else
                {
                    vorhersageTag = (lastDay - date.Day) + 1;
                }

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
}
