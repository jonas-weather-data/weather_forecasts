using System;
using System.Collections.Generic;
using System.Data;
using Microsoft.Data.SqlClient;

public class ForecastEvaluator
{
    private readonly string _connectionString =
        "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;";

    private readonly ObservationRepository _obsRepo;

    public ForecastEvaluator()
    {
        _obsRepo = new ObservationRepository();
    }

    // Ergebnisobjekt für ein Modell / Tag / Vorhersagehorizont
    public record ForecastErrorPoint(
        DateTime Datum,
        string Modell,
        int VorhersageTag,
        decimal Prognose,
        decimal Beobachtung,
        decimal Fehler
    );

    // Lädt alle Prognosen eines Monats + Beobachtungen und berechnet Fehler
    public List<ForecastErrorPoint> EvaluateMonth(int year, int month)
    {
        var result = new List<ForecastErrorPoint>();

        // Beobachtungen laden
        var obsTmk = _obsRepo.GetObservedTmk(year, month);

        using var conn = new SqlConnection(_connectionString);
        using var cmd = new SqlCommand(@"
            SELECT Datum, Modell, VorhersageTag, TmkPrognose
            FROM modellprognosen
            WHERE YEAR(Datum) = @y
              AND MONTH(Datum) = @m
            ORDER BY Datum, Modell, VorhersageTag;
        ", conn);

        cmd.Parameters.Add("@y", SqlDbType.Int).Value = year;
        cmd.Parameters.Add("@m", SqlDbType.Int).Value = month;

        conn.Open();
        using var reader = cmd.ExecuteReader();

        while (reader.Read())
        {
            var datum = reader.GetDateTime(0);
            var modell = reader.GetString(1);
            var vorh = reader.GetInt32(2);
            var prognose = reader.IsDBNull(3) ? 0m : reader.GetDecimal(3);

            if (!obsTmk.TryGetValue(datum, out var beob))
                continue;

            var fehler = prognose - beob;

            result.Add(new ForecastErrorPoint(
                datum,
                modell,
                vorh,
                prognose,
                beob,
                fehler
            ));
        }

        return result;
    }
}
