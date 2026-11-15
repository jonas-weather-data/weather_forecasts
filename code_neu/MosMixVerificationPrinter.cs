using System;
using System.Collections.Generic;
using System.Data;
using System.Data.SqlClient;
using System.Globalization;
using System.Linq;
using System.Text;

public class MosmixVerificationPrinter
{
    private readonly string _connectionString =
        "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;";

    // ---------------------------------------------------------
    //  Hilfsfunktion: Normalisiert Stationsnamen
    // ---------------------------------------------------------
    private string Normalize(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return "";

        name = name.Trim().ToUpperInvariant();

        // BAD‑Regel
        // MOSMIX: BAD LIPPSPRINGE
        // DWD:    LIPPSPRINGE, BAD
        if (name.StartsWith("BAD "))
        {
            // BAD LIPPSPRINGE → LIPPSPRINGE BAD
            name = name.Substring(4) + " BAD";
        }
        else if (name.Contains(", BAD"))
        {
            // LIPPSPRINGE, BAD → BAD LIPPSPRINGE
            name = "BAD " + name.Replace(", BAD", "");
        }

        // Umlaute
        name = name.Replace("Ä", "AE")
                   .Replace("Ö", "OE")
                   .Replace("Ü", "UE")
                   .Replace("ß", "SS");

        // Nur Buchstaben/Ziffern
        var sb = new StringBuilder();
        foreach (char c in name)
            if (char.IsLetterOrDigit(c))
                sb.Append(c);

        return sb.ToString();
    }


    // ---------------------------------------------------------
    //  Holt heutige Messwerte aus SQL
    // ---------------------------------------------------------
    private List<(string Station, string Bundesland, double Tx)> LoadTodayMeasurements()
    {
        var result = new List<(string Station, string Bundesland, double Tx)>();

        using var conn = new SqlConnection(_connectionString);
        conn.Open();

        string sql = @"
            select s.name, b.name as Bundesland, max(tx10_tmax) as Tx
            from stationen s
            join extrema e on s.station_id = e.station_id
            join bundeslaender b on s.bundesland_id = b.id
            where cast(e.mess_Datum as date) = cast(getdate() as date)
            group by s.name, b.name
            order by s.name, b.name;
        ";

        using var cmd = new SqlCommand(sql, conn);
        using var rd = cmd.ExecuteReader();

        while (rd.Read())
        {
            string station = rd.GetString(0);
            string bundesland = rd.GetString(1);

            double tx;
            if (rd.IsDBNull(2))
            {
                tx = double.NaN;
            }
            else
            {
                // FIX: DECIMAL → double
                tx = Convert.ToDouble(rd.GetDecimal(2), CultureInfo.InvariantCulture);
            }

            result.Add((station, bundesland, tx));
        }

        return result;
    }

    // ---------------------------------------------------------
    //  Holt Durchschnitt Messwert
    // ---------------------------------------------------------
    private double LoadTodayMeasurementAverage()
    {
        using var conn = new SqlConnection(_connectionString);
        conn.Open();

        string sql = @"
            select avg(tx10_tmax)
            from extrema
            where cast(mess_Datum as date) = cast(getdate() as date);
        ";

        using var cmd = new SqlCommand(sql, conn);
        object val = cmd.ExecuteScalar();

        if (val == DBNull.Value || val == null)
            return double.NaN;

        return Convert.ToDouble(val, CultureInfo.InvariantCulture);
    }

    // ---------------------------------------------------------
    //  Hauptmethode: Vergleicht MOSMIX mit Messwerten
    // ---------------------------------------------------------
    public void PrintMosmixVsMeasurements(
        List<MosmixParser.StationData> mosmixStations,
        DateTime today)
    {
        DateTime day = today.Date;

        // 1) Messwerte laden
        var measurements = LoadTodayMeasurements();

        // 2) MOSMIX nur deutsche Stationen
        var mosmixDE = MosmixParser.FilterGermany(mosmixStations).ToList();

        // 3) Mapping vorbereiten
        var mosmixDict = mosmixDE
            .Select(st => new
            {
                Original = st.Name,
                Norm = Normalize(st.Name),
                Tmax = st.DailyMaxTemp.TryGetValue(day, out double tx)
                        ? tx
                        : st.TempCPerHour
                            .Where(kv => kv.Key.Date == day)
                            .Select(kv => kv.Value)
                            .DefaultIfEmpty(double.NaN)
                            .Max()
            })
            .Where(x => !double.IsNaN(x.Tmax))
            .ToList();

        // 4) Vergleichsliste erzeugen
        var comparison = new List<(string Station, string Bundesland, double Prognose, double Messwert, double Diff)>();

        foreach (var m in measurements)
        {
            string norm = Normalize(m.Station);

            var match = mosmixDict.FirstOrDefault(x => x.Norm == norm);

            if (match == null)
                continue; // Station nicht in MOSMIX

            double diff = m.Tx - match.Tmax;

            comparison.Add((m.Station, m.Bundesland, match.Tmax, m.Tx, diff));
        }

        // 5) Sortieren nach größter positiver Abweichung
        comparison = comparison
            .OrderByDescending(x => x.Diff)
            .ToList();

        // 6) Durchschnitt MOSMIX
        double avgMosmix = comparison.Select(x => x.Prognose).Average();

        // 7) Durchschnitt Messwerte
        double avgMess = LoadTodayMeasurementAverage();

        // ---------------------------------------------------------
        //  Ausgabe
        // ---------------------------------------------------------
        Console.WriteLine();
        Console.WriteLine("=== MOSMIX vs. Messwerte – Tageshöchsttemperatur (Tmax) ===");
        Console.WriteLine($"Datum: {day:dd.MM.yyyy}");
        Console.WriteLine();

        Console.WriteLine($"{"Station",-30} {"Bundesland",-15} {"MOSMIX",8} {"Messung",8} {"Diff",8}");
        Console.WriteLine(new string('-', 75));

        foreach (var c in comparison)
        {
            Console.WriteLine($"{c.Station,-30} {c.Bundesland,-15} {c.Prognose,8:F1} {c.Messwert,8:F1} {c.Diff,8:F1}");
        }

        Console.WriteLine(new string('-', 75));
        Console.WriteLine($"{"Durchschnitt",-30} {"",-15} {avgMosmix,8:F1} {avgMess,8:F1} {(avgMess - avgMosmix),8:F1}");
        Console.WriteLine();
    }

    public void SaveMosmixForecastForTomorrow(
        List<MosmixParser.StationData> stations,
        DateTime today)
    {
        DateTime tomorrow = today.AddDays(1).Date;

        var germanStations = MosmixParser.FilterGermany(stations).ToList();

        using var con = new SqlConnection(_connectionString);
        con.Open();

        foreach (var st in germanStations)
        {
            // station_id aus deiner DB holen
            string? stationId = GetStationIdFromDb(st.Name, con);
            if (stationId == null)
                continue;

            // Tmax für morgen holen
            if (!st.DailyMaxTemp.TryGetValue(tomorrow, out double tmax))
                continue;

            var cmd = new SqlCommand(@"
        INSERT INTO mosmix_prognosen (station_id, prognose_datum, laufzeit, tmax_prognose)
        VALUES (@sid, @datum, @lauf, @tmax)", con);

            cmd.Parameters.AddWithValue("@sid", stationId);
            cmd.Parameters.AddWithValue("@datum", tomorrow);
            cmd.Parameters.AddWithValue("@lauf", new DateTime(
                today.Year,
                today.Month,
                today.Day,
                15, 0, 0,
                DateTimeKind.Utc));

            cmd.Parameters.AddWithValue("@tmax", tmax);

            cmd.ExecuteNonQuery();
        }
    }

    private string? GetStationIdFromDb(string stationName, SqlConnection con)
    {
        var cmd = new SqlCommand(
            "SELECT station_id FROM stationen WHERE name = @name", con);
        cmd.Parameters.AddWithValue("@name", stationName);

        var result = cmd.ExecuteScalar();
        return result == null ? null : result.ToString();
    }

    public void CompareMosmixWithObserved(
        DateTime today)
    {
        DateTime day = today.Date;

        using var con = new SqlConnection(_connectionString);
        con.Open();

        // Prognosen von gestern holen
        var prognosen = new Dictionary<string, double>();
        var cmd1 = new SqlCommand(@"
    SELECT station_id, tmax_prognose
    FROM mosmix_prognosen
    WHERE prognose_datum = @day", con);
        cmd1.Parameters.AddWithValue("@day", day);

        using (var r = cmd1.ExecuteReader())
            while (r.Read())
                prognosen[r.GetString(0).Trim()] = r.GetDouble(1);

        // Messwerte holen
        var messwerte = new Dictionary<string, double>();
        var cmd2 = new SqlCommand(@"
    SELECT station_id, txk
    FROM extrema
    WHERE mess_datum = @day", con);
        cmd2.Parameters.AddWithValue("@day", day);

        using (var r = cmd2.ExecuteReader())
            while (r.Read())
                messwerte[r.GetString(0).Trim()] = r.GetDouble(1);

        // Vergleich
        var diffs = new List<double>();
        var absDiffs = new List<double>();
        var prognoseList = new List<double>();
        var messwertList = new List<double>();

        foreach (var kv in prognosen)
        {
            string sid = kv.Key;
            double p = kv.Value;

            if (!messwerte.TryGetValue(sid, out double m))
                continue;

            prognoseList.Add(p);
            messwertList.Add(m);

            double diff = p - m;
            diffs.Add(diff);
            absDiffs.Add(Math.Abs(diff));
        }

        if (prognoseList.Count == 0)
        {
            Console.WriteLine("Keine Vergleichsdaten verfügbar.");
            return;
        }

        double avgP = prognoseList.Average();
        double avgM = messwertList.Average();
        double avgDiff = diffs.Average();
        double avgAbsDiff = absDiffs.Average();

        Console.WriteLine();
        Console.WriteLine("=== MOSMIX Verifikation ===");
        Console.WriteLine($"Tag: {day:dd.MM.yyyy}");
        Console.WriteLine();
        Console.WriteLine($"Durchschnitt Prognose: {avgP:F1} °C");
        Console.WriteLine($"Durchschnitt Messwert: {avgM:F1} °C");
        Console.WriteLine($"Abweichung (signed):   {avgDiff:F1} °C");
        Console.WriteLine($"Abweichung (abs):      {avgAbsDiff:F1} °C");
        Console.WriteLine();
    }


    public void UpdateMosmixStationMapping(List<MosmixParser.StationData> mosmixStations)
    {
        using var conn = new SqlConnection(_connectionString);
        conn.Open();

        // 1) DWD‑Stationen laden, die gestern/ab Tag X Höchstwerte hatten UND noch nicht gemappt sind
        var measuredYesterdayNorm = new Dictionary<string, string>();   // station_id -> normalized name
        var measuredYesterdayRaw = new Dictionary<string, string>();   // station_id -> original name
        var dwdHeights = new Dictionary<string, int>();      // station_id -> height

        var day = new DateTime(2026, 6, 19); // oder: DateTime.Today.AddDays(-1);

        using (var cmd = new SqlCommand(@"
        SELECT s.station_id, s.name, s.stationshoehe
        FROM stationen s
        WHERE s.station_id IN (
            SELECT DISTINCT station_id
            FROM extrema
            WHERE tx10_tmax IS NOT NULL
              AND mess_datum >= @dayStart
        )
        AND s.station_id NOT IN (
            SELECT station_id FROM mosmix_station_mapping
        )
        ORDER BY s.name;
    ", conn))
        {
            cmd.Parameters.Add("@dayStart", SqlDbType.DateTime).Value = day;

            using (var rd = cmd.ExecuteReader())
            {
                while (rd.Read())
                {
                    string id = rd.GetString(0);
                    string name = rd.GetString(1);
                    int height = rd.IsDBNull(2) ? 0 : rd.GetInt32(2);

                    measuredYesterdayRaw[id] = name;
                    measuredYesterdayNorm[id] = Normalize(name);
                    dwdHeights[id] = height;
                }
            }
        }

        // 2) MOSMIX‑Stationen vorbereiten (Index merken für „früheste in Datei“)
        var mosmixList = mosmixStations
            .Select((st, idx) => new
            {
                Index = idx,
                Code = st.Code,
                Name = st.Name,
                Norm = Normalize(st.Name),
                Height = st.Height
            })
            .ToList();

        // 3) Matching + Insert (aggressiver, im Zweifel lieber falsch als gar nicht)
        foreach (var kv in measuredYesterdayNorm)
        {
            string stationId = kv.Key;
            string dwdNorm = kv.Value;
            string dwdName = measuredYesterdayRaw[stationId];
            int dwdHeight = dwdHeights.TryGetValue(stationId, out var h) ? h : 0;

            // 3.1 Kandidaten: exakter Normalized‑Name
            var candidates = mosmixList
                .Where(m => m.Norm == dwdNorm)
                .ToList();

            // 3.2 Wenn keine exakten: über Stadt‑/Hauptteil‑Key (z.B. EMMENDINGEN, ESSEN, ESCHWEGE)
            if (candidates.Count == 0)
            {
                string cityKey = ExtractCityKey(dwdName);      // z.B. "Emmendingen" aus "Emmendingen-Mundingen"
                string cityNorm = Normalize(cityKey);          // EMMENDINGEN

                candidates = mosmixList
                    .Where(m =>
                        m.Norm.StartsWith(cityNorm) ||         // ESSEN..., EMMENDINGEN...
                        cityNorm.StartsWith(m.Norm))           // falls MOSMIX kürzer ist
                    .ToList();
            }

            // 3.3 Wenn immer noch nichts: letzte Eskalation – alles, was den CityKey irgendwo enthält
            if (candidates.Count == 0)
            {
                string cityKey = ExtractCityKey(dwdName);
                string cityNorm = Normalize(cityKey);

                candidates = mosmixList
                    .Where(m => m.Norm.Contains(cityNorm))
                    .ToList();
            }

            if (candidates.Count == 0)
            {
                Console.WriteLine($"NO MATCH: {stationId} ({dwdName})");
                continue;
            }

            // 3.4 Beste Station nach Höhe wählen, bei Gleichstand die früheste in der Datei
            var ranked = candidates
                .Select(m => new
                {
                    Item = m,
                    Diff = Math.Abs(Math.Round(m.Height) - dwdHeight)
                })
                .OrderBy(x => x.Diff)
                .ThenBy(x => x.Item.Index)   // bei gleicher Diff: früheste in Datei
                .ToList();

            var chosen = ranked[0].Item;    // IM ZWEIFEL lieber falsch als gar nicht

            try
            {
                using var insert = new SqlCommand(@"
        INSERT INTO mosmix_station_mapping (station_id, mosmix_code, mosmix_name)
        VALUES (@id, @code, @name)", conn);

                insert.Parameters.Add("@id", SqlDbType.VarChar, 10).Value = stationId;
                insert.Parameters.Add("@code", SqlDbType.VarChar, 10).Value = (object)chosen.Code ?? DBNull.Value;
                insert.Parameters.Add("@name", SqlDbType.VarChar, 200).Value = (object)chosen.Name ?? DBNull.Value;

                insert.ExecuteNonQuery();

                Console.WriteLine($"MATCH: {stationId} -> {chosen.Code} ({chosen.Name})");
            }
            catch (SqlException ex) when (ex.Number == 2627 || ex.Number == 2601)
            {
                // 2627 = Unique constraint violation
                // 2601 = Duplicate key row error
                Console.WriteLine($"SKIPPED (ALREADY MAPPED): {stationId} -> {chosen.Code}");
                // einfach weitermachen
            }


            Console.WriteLine($"MATCH: {stationId} ({dwdName}) -> {chosen.Code} ({chosen.Name}), ΔH={Math.Abs(Math.Round(chosen.Height) - dwdHeight)}");
        }
    }

    // zieht den „Hauptteil“ des Namens, z.B. Emmendingen aus „Emmendingen-Mundingen“, Essen aus „Essen-Bredeney“
    private string ExtractCityKey(string name)
    {
        if (string.IsNullOrWhiteSpace(name))
            return "";

        var s = name.Trim();

        // bis erstes Komma
        int comma = s.IndexOf(',');
        if (comma > 0)
            s = s.Substring(0, comma);

        // bis erstes Leerzeichen
        int space = s.IndexOf(' ');
        if (space > 0)
            s = s.Substring(0, space);

        // bis erster Bindestrich
        int dash = s.IndexOf('-');
        if (dash > 0)
            s = s.Substring(0, dash);

        return s.Trim();
    }





}
