using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using Microsoft.Data.SqlClient;

public class MosmixBundeslandDailyPrinter
{
    private readonly string _connectionString =
        "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;";

    private Dictionary<string, string> LoadMosmixBundeslandMapping()
    {
        var dict = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        using var conn = new SqlConnection(_connectionString);
        conn.Open();

        using var cmd = new SqlCommand(@"
            SELECT m.mosmix_code, b.name
            FROM mosmix_station_mapping m
            JOIN stationen s ON s.station_id = m.station_id
            JOIN bundeslaender b ON b.id = s.bundesland_id
        ", conn);

        using var rd = cmd.ExecuteReader();
        while (rd.Read())
        {
            string code = rd.GetString(0);
            string bundesland = rd.GetString(1);
            dict[code] = bundesland;
        }

        return dict;
    }

    public void PrintBundeslandDailyMeans(MosmixData mosmix)
    {
        var blMap = LoadMosmixBundeslandMapping();

        var days = mosmix.AllStations
            .SelectMany(st => st.TempCPerHour.Keys.Select(d => d.Date))
            .Distinct()
            .OrderBy(d => d)
            .ToList();

        // letzten Tag entfernen (wie überall sonst)
        if (days.Count > 0)
            days.RemoveAt(days.Count - 1);

        Console.WriteLine("=== MOSMIX Tagesmittel + kumulierte Werte pro Bundesland und Tag ===");
        Console.WriteLine();

        var cum = new Dictionary<string, (double tempSum, int tempCount,
                                          double sunSum, double rainSum)>();

        var tempSeries = new Dictionary<string, List<(DateTime date, double daily, double cum)>>();
        var sunSeries = new Dictionary<string, List<(DateTime date, double daily, double cum)>>();
        var rainSeries = new Dictionary<string, List<(DateTime date, double daily, double cum)>>();

        foreach (var date in days)
        {
            Console.WriteLine(date.ToString("yyyy-MM-dd"));
            Console.WriteLine($"{"Bundesland",-20} {"Temp",-8} {"TempKum",-10} {"Sonne",-8} {"SonneKum",-10} {"Regen",-8} {"RegenKum",-10}");

            var daily = new Dictionary<string, (double tempSum, double sunSum, double rainSum, int stationCount)>();

            foreach (var st in mosmix.AllStations)
            {
                if (!blMap.TryGetValue(st.Code, out var bl))
                    continue;

                var dayTemps = st.TempCPerHour
                    .Where(x => x.Key.Date == date.Date)
                    .Select(x => x.Value)
                    .ToList();

                if (dayTemps.Count == 0)
                    continue;

                double stationTmean = dayTemps.Average();

                double sunHours = st.SunshineSecondsPerHour
                    .Where(x => x.Key.Date == date.Date)
                    .Sum(x => x.Value) / 3600.0;

                double rainMm = st.RainMmPerHour
                    .Where(x => x.Key.Date == date.Date)
                    .Sum(x => x.Value);

                if (!daily.ContainsKey(bl))
                    daily[bl] = (0, 0, 0, 0);

                var d = daily[bl];
                d.tempSum += stationTmean;
                d.sunSum += sunHours;
                d.rainSum += rainMm;
                d.stationCount++;
                daily[bl] = d;
            }

            foreach (var bl in daily.Keys.OrderBy(x => x))
            {
                var d = daily[bl];

                double tempMean = d.stationCount > 0 ? d.tempSum / d.stationCount : double.NaN;
                double sunMean = d.stationCount > 0 ? d.sunSum / d.stationCount : double.NaN;
                double rainMean = d.stationCount > 0 ? d.rainSum / d.stationCount : double.NaN;

                if (!cum.ContainsKey(bl))
                    cum[bl] = (0, 0, 0, 0);

                var c = cum[bl];

                c.tempSum += tempMean;
                c.tempCount++;
                double tempKum = c.tempSum / c.tempCount;

                c.sunSum += sunMean;
                double sunKum = c.sunSum;

                c.rainSum += rainMean;
                double rainKum = c.rainSum;

                cum[bl] = c;

                Console.WriteLine($"{bl,-20} {tempMean,8:F2} {tempKum,10:F2} {sunMean,8:F1} {sunKum,10:F1} {rainMean,8:F1} {rainKum,10:F1}");

                if (!tempSeries.ContainsKey(bl))
                {
                    tempSeries[bl] = new List<(DateTime, double, double)>();
                    sunSeries[bl] = new List<(DateTime, double, double)>();
                    rainSeries[bl] = new List<(DateTime, double, double)>();
                }

                tempSeries[bl].Add((date, tempMean, tempKum));
                sunSeries[bl].Add((date, sunMean, sunKum));
                rainSeries[bl].Add((date, rainMean, rainKum));
            }

            Console.WriteLine();
        }

        var tempDiagram = new TempBundeslandDiagramService();
        var sunDiagram = new SunBundeslandDiagramService();
        var rainDiagram = new RainBundeslandDiagramService();

        tempDiagram.Create(tempSeries);
        sunDiagram.Create(sunSeries);
        rainDiagram.Create(rainSeries);

    }
}
