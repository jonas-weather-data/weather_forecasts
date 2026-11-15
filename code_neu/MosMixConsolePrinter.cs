using Microsoft.Data.SqlClient;
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

public class MosmixConsolePrinter
{
    private static readonly string[] WantedOrder =
        {
            "SCHLESWIG",
            "KIEL-H.",
            "ARKONA",
            "HAMBURG-NEUENG.",
            "POTSDAM",
            "BREMEN",
            "BEVERN",
            "BIELEFELD-DEPPENDORF",
            "DIEPHOLZ",
            "WERL",
            "GOETTINGEN",
            "LEINEFELDE",
            "DRESDEN-HOSTERWITZ",
            "GOERLITZ",
            "BONN-ROLEBER",
            "FRANKFURT/M",
            "SCHMELZ-HUETTERSDORF",
            "BERUS",
            "NUERNBERG",
            "STUTTGART-SCHN.",
            "FREIBURG",
            "MUENCHEN STADT"
        };


    public void PrintSunshine16Stations(
        Dictionary<string, (double Total, Dictionary<int, double> Days)> data,
        Dictionary<DateTime, double> germanyDailyMean,
        DateTime today)
    {
        int year = today.Year;
        int month = today.Month;
        int todayDay = today.Day;

        // Nur Tage drucken, die MOSMIX tatsächlich liefert
        int lastMosmixDay = data
            .SelectMany(s => s.Value.Days.Keys)
            .DefaultIfEmpty(todayDay)
            .Max();

        Console.WriteLine();
        Console.WriteLine("=== MOSMIX Sonnenschein – Deutschlandmittel + 16 Stationen (Gesamt + Tageswerte) ===");
        Console.WriteLine();

        int colWidthStation = 25;
        int colWidthValue = 8;

        // Kopfzeile
        Console.Write("Station".PadRight(colWidthStation));
        Console.Write("Gesamt".PadRight(colWidthValue));
        for (int d = todayDay; d <= lastMosmixDay; d++)
            Console.Write($"{d:00}".PadLeft(6));
        Console.WriteLine();

        // =========================
        // Deutschlandmittel-Zeile
        // =========================
        var germanyDays = germanyDailyMean
            .Where(kv => kv.Key.Year == year && kv.Key.Month == month && kv.Key.Day >= todayDay && kv.Key.Day <= lastMosmixDay)
            .OrderBy(kv => kv.Key.Day)
            .ToDictionary(kv => kv.Key.Day, kv => kv.Value);

        double germanyTotal = germanyDays.Values.Sum();

        Console.Write("DEUTSCHLAND-MITTEL".PadRight(colWidthStation));
        Console.Write($"{germanyTotal,7:F1} ");
        for (int d = todayDay; d <= lastMosmixDay; d++)
        {
            if (germanyDays.TryGetValue(d, out double h))
                Console.Write($"{h,6:F1}");
            else
                Console.Write("     -");
        }
        Console.WriteLine();

        // =========================
        // Stations-Zeilen
        // =========================
        foreach (var w in WantedOrder)
        {
            var entry = data[w];
            Console.Write(w.PadRight(colWidthStation));

            // Gesamtwert exakt als Summe der Einzelwerte
            double total = entry.Days.Values.Sum();
            Console.Write($"{total,7:F1} ");

            for (int d = todayDay; d <= lastMosmixDay; d++)
            {
                if (entry.Days.TryGetValue(d, out double h))
                    Console.Write($"{h,6:F1}");
                else
                    Console.Write("     -");
            }

            Console.WriteLine();
        }

        Console.WriteLine();
    }

    public void PrintTop10WarmestStationsForNextDay(
    List<MosmixParser.StationData> stations,
    DateTime today,
    bool allDays = false)
    {
        var germanStations = MosmixParser.FilterGermany(stations).ToList();

        if (!allDays)
        {
            PrintForSingleDayWithHeatCheck(germanStations, today.AddDays(1).Date);
            return;
        }

        var allDaysAvailable = germanStations
            .SelectMany(st => st.DailyMaxTemp.Keys.Select(d => d.Date))
            .Distinct()
            .OrderBy(d => d)
            .ToList();

        foreach (var day in allDaysAvailable)
            PrintForSingleDayWithHeatCheck(germanStations, day);
    }

    private void PrintForSingleDayWithHeatCheck(
        List<MosmixParser.StationData> stations,
        DateTime day)
    {
        var list = new List<(string Station, double Tmax)>();

        foreach (var st in stations)
        {
            double tmax;

            if (st.DailyMaxTemp.TryGetValue(day, out double txValue))
            {
                tmax = txValue;
            }
            else
            {
                var values = st.TempCPerHour
                               .Where(kv => kv.Key.Date == day)
                               .Select(kv => kv.Value)
                               .ToList();

                if (values.Count == 0)
                    continue;

                tmax = values.Max();
            }

            list.Add((st.Name, tmax));
        }

        // NEU: alle >= 40°C
        var over40 = list
            .Where(x => x.Tmax >= 40.0)
            .OrderByDescending(x => x.Tmax)
            .ToList();

        List<(string Station, double Tmax)> output;

        if (over40.Count >= 10)
        {
            output = over40;
        }
        else
        {
            output = list
                .OrderByDescending(x => x.Tmax)
                .Take(10)
                .ToList();
        }

        Console.WriteLine();
        Console.WriteLine($"=== Wärmste Stationen (Tmax) für {day:dd.MM.yyyy} ===");
        Console.WriteLine();

        foreach (var entry in output)
            Console.WriteLine($"{entry.Station,-35} {entry.Tmax,6:F1} °C");

        Console.WriteLine();
    }


    public void PrintRegionTopsForNextDay(
    List<MosmixParser.StationData> stations,
    DateTime today,
    bool allDays = false)
    {
        var germanStations = MosmixParser.FilterGermany(stations).ToList();

        // --- Bundesland-Mapping laden ---
        var stationToBundesland = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        using (var conn = new SqlConnection(
               "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;"))
        {
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

                if (string.Equals(code, "P101", StringComparison.OrdinalIgnoreCase))
                    continue;

                stationToBundesland[code] = bundesland;
            }
        }

        // --- Regionen definieren ---
        var regionMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["Schleswig-Holstein"] = "Nord",
            ["Hamburg"] = "Nord",
            ["Mecklenburg-Vorpommern"] = "Nord",

            ["Niedersachsen"] = "Nordwest",
            ["Bremen"] = "Nordwest",

            ["Sachsen-Anhalt"] = "Ost",
            ["Brandenburg"] = "Ost",
            ["Berlin"] = "Ost",

            ["Nordrhein-Westfalen"] = "NRW",

            ["Hessen"] = "Mitte",
            ["Thüringen"] = "Mitte",
            ["Sachsen"] = "Mitte",

            ["Saarland"] = "Südwest",
            ["Rheinland-Pfalz"] = "Südwest",

            ["Baden-Württemberg"] = "BW",

            ["Bayern"] = "Bayern"
        };

        // --- Tagesliste bestimmen ---
        List<DateTime> days;

        if (!allDays)
        {
            days = new List<DateTime> { today.AddDays(1).Date };
        }
        else
        {
            days = germanStations
                .SelectMany(st => st.DailyMaxTemp.Keys.Select(d => d.Date))
                .Distinct()
                .OrderBy(d => d)
                .ToList();
        }

        // --- Ausgabe pro Tag ---
        foreach (var day in days)
        {
            Console.WriteLine();
            Console.WriteLine($"=== Wärmste Station je Region für {day:dd.MM.yyyy} ===");

            var best = new Dictionary<string, (string Station, double Tmax)>();
            var allTmaxValues = new List<double>();

            foreach (var st in germanStations)
            {
                if (!stationToBundesland.TryGetValue(st.Code, out var bundesland))
                    continue;

                if (!regionMap.TryGetValue(bundesland, out var region))
                    continue;

                double tmax;

                if (st.DailyMaxTemp.TryGetValue(day, out var tx))
                {
                    tmax = tx;
                }
                else
                {
                    var vals = st.TempCPerHour
                        .Where(kv => kv.Key.Date == day)
                        .Select(kv => kv.Value)
                        .ToList();

                    if (vals.Count == 0)
                        continue;

                    tmax = vals.Max();
                }

                allTmaxValues.Add(tmax);

                if (!best.ContainsKey(region) || tmax > best[region].Tmax)
                    best[region] = (st.Name, tmax);
            }

            double avgTmax = allTmaxValues.Count > 0 ? allTmaxValues.Average() : double.NaN;
            Console.WriteLine($"Durchschnittliche Höchsttemperatur aller Stationen: {avgTmax:F1} °C");
            Console.WriteLine();

            foreach (var kv in best.OrderBy(k => k.Key))
                Console.WriteLine($"{kv.Key,-12} {kv.Value.Station,-30} {kv.Value.Tmax,6:F1} °C");

            Console.WriteLine();
        }
    }

    public void PrintStationsWithDailyHeatwave30Plus(List<MosmixParser.StationData> stations)
    {
        var germanStations = MosmixParser.FilterGermany(stations).ToList();

        // --- Bundesland- und DWD-Stationsnamen-Mapping laden ---
        var stationInfo = new Dictionary<string, (string Bundesland, string Name)>(StringComparer.OrdinalIgnoreCase);

        using (var conn = new SqlConnection(
               "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;"))
        {
            conn.Open();

            using var cmd = new SqlCommand(@"
        SELECT m.mosmix_code, b.name, s.name
        FROM mosmix_station_mapping m
        JOIN stationen s ON s.station_id = m.station_id
        JOIN bundeslaender b ON b.id = s.bundesland_id
    ", conn);

            using var rd = cmd.ExecuteReader();
            while (rd.Read())
            {
                string code = rd.GetString(0); // MOSMIX-Code
                string bundesland = rd.GetString(1); // Bundesland
                string stationName = rd.GetString(2); // DWD-Stationen.name

                stationInfo[code] = (bundesland, stationName);
            }
        }

        // --- Alle Tage bestimmen, die MOSMIX liefert (nur Zukunft) ---
        var allDays = germanStations
            .SelectMany(st => st.DailyMaxTemp.Keys.Select(d => d.Date))
            //.Where(d => d > DateTime.Today)
            .Distinct()
            .OrderBy(d => d)
            .ToList();

        var headerDates = allDays
            .Select(d => d.ToString("dd.MM.", CultureInfo.InvariantCulture))
            .ToList();

        const int colWidth = 8; // gemeinsame Spaltenbreite für Datum und Wert

        // kleine Hilfsfunktion zum Zentrieren
        static string Center(string text, int width)
        {
            if (text.Length >= width) return text;
            int left = (width - text.Length) / 2;
            int right = width - text.Length - left;
            return new string(' ', left) + text + new string(' ', right);
        }

        Console.WriteLine("=== Stationen mit durchgehend >= 30,0°C an allen MOSMIX-Tagen ===");
        Console.WriteLine();

        // Header: Bundesland, Station, dann zentrierte Datums-Spalten
        Console.Write($"{"Bundesland",-20} {"Station",-30}");
        foreach (var h in headerDates)
            Console.Write(Center(h, colWidth));
        Console.WriteLine();

        // --- Ergebnisliste ---
        var result = new List<(string Bundesland, string Station, List<double> Values)>();

        foreach (var st in germanStations)
        {
            if (!stationInfo.TryGetValue(st.Code, out var info))
                continue;

            var values = new List<double>();
            bool allAbove30 = true;

            foreach (var day in allDays)
            {
                if (st.DailyMaxTemp.TryGetValue(day, out double tmax))
                {
                    values.Add(tmax);
                    if (tmax < 30.0)
                    {
                        allAbove30 = false;
                        break;
                    }
                }
                else
                {
                    allAbove30 = false;
                    break;
                }
            }

            if (allAbove30)
                result.Add((info.Bundesland, info.Name, values)); // DWD-Stationname
        }

        // --- Sortieren ---
        result = result
            .OrderBy(r => r.Bundesland)
            .ThenBy(r => r.Station)
            .ToList();

        // --- Ausgabe ---
        Console.WriteLine();

        foreach (var entry in result)
        {
            Console.Write($"{entry.Bundesland,-20} {entry.Station,-30}");
            foreach (var v in entry.Values)
                Console.Write(Center(v.ToString("0.0"), colWidth));
            Console.WriteLine();
        }

        Console.WriteLine();
    }




    public void PrintAverageTmaxForToday(List<MosmixParser.StationData> stations, DateTime today)
    {
        DateTime day = today.Date;

        // Nur deutsche Stationen
        var germanStations = MosmixParser.FilterGermany(stations).ToList();

        var tmaxValues = new List<double>();

        foreach (var st in germanStations)
        {
            double tmax;

            // 1) Bevorzugt TX (echtes Tagesmaximum)
            if (st.DailyMaxTemp.TryGetValue(day, out double txValue))
            {
                tmax = txValue;
            }
            else
            {
                // 2) Fallback: höchster Stundenwert aus TTT
                var values = st.TempCPerHour
                               .Where(kv => kv.Key.Date == day)
                               .Select(kv => kv.Value)
                               .ToList();

                if (values.Count == 0)
                    continue;

                tmax = values.Max();
            }

            tmaxValues.Add(tmax);
        }

        if (tmaxValues.Count == 0)
        {
            Console.WriteLine($"Keine Temperaturdaten für {day:dd.MM.yyyy} verfügbar.");
            return;
        }

        double avg = tmaxValues.Average();

        Console.WriteLine();
        Console.WriteLine($"=== Durchschnittliche Tageshöchsttemperatur (Tmax) für {day:dd.MM.yyyy} ===");
        Console.WriteLine();
        Console.WriteLine($"Mittelwert aus {tmaxValues.Count} Stationen: {avg:F2} °C");
        Console.WriteLine();
    }


    private void PrintForSingleDay(
        List<MosmixParser.StationData> stations,
        DateTime day)
    {
        var list = new List<(string Station, double Tmax)>();

        foreach (var st in stations)
        {
            double tmax;

            // 1) Bevorzugt TX (echtes Tagesmaximum)
            if (st.DailyMaxTemp.TryGetValue(day, out double txValue))
            {
                tmax = txValue;
            }
            else
            {
                // 2) Fallback: höchster Stundenwert aus TTT
                var values = st.TempCPerHour
                               .Where(kv => kv.Key.Date == day)
                               .Select(kv => kv.Value)
                               .ToList();

                if (values.Count == 0)
                    continue;

                tmax = values.Max();
            }

            list.Add((st.Name, tmax));
        }

        var top10 = list
            .OrderByDescending(x => x.Tmax)
            .Take(10)
            .ToList();

        Console.WriteLine();
        Console.WriteLine($"=== Top 10 wärmste Stationen (Tmax) für {day:dd.MM.yyyy} ===");
        Console.WriteLine();

        foreach (var entry in top10)
            Console.WriteLine($"{entry.Station,-35} {entry.Tmax,6:F1} °C");

        Console.WriteLine();
    }



}
