using System;
using System.Collections.Generic;
using System.Data;
using Microsoft.Data.SqlClient;

public class ObservationRepository
{
    private readonly string _connectionString =
        "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;";

    // tagesmittel_2: bundeslandid, jahr, monat, tag, tmk
    public Dictionary<DateTime, decimal> GetObservedTmk(int year, int month)
    {
        var result = new Dictionary<DateTime, decimal>();

        using var conn = new SqlConnection(_connectionString);
        using var cmd = new SqlCommand(@"
            SELECT jahr, monat, tag, tmk
            FROM tagesmittel_2
            WHERE jahr = @y
              AND monat = @m
              AND bundeslandid = 17
            ORDER BY tag;
        ", conn);

        cmd.Parameters.Add("@y", SqlDbType.Int).Value = year;
        cmd.Parameters.Add("@m", SqlDbType.Int).Value = month;

        conn.Open();
        using var reader = cmd.ExecuteReader();

        while (reader.Read())
        {
            int y = reader.GetInt32(0);
            int mo = reader.GetInt32(1);
            int d = reader.GetInt32(2);

            var date = new DateTime(y, mo, d);
            var value = reader.IsDBNull(3) ? 0m : reader.GetDecimal(3);

            result[date] = value;
        }

        return result;
    }
}
