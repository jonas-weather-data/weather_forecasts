using System;
using System.Data;
using Microsoft.Data.SqlClient;

public class TestModeForecastRepository
{
    private readonly string _connectionString =
        "Data Source=localhost;Initial Catalog=dwd_daten;User ID=sa;Password=phoenix;Encrypt=False;TrustServerCertificate=True;";

    private bool _cleared = false;

    private void ClearTableIfNeeded(SqlConnection conn)
    {
        if (_cleared)
            return;

        using var cmd = new SqlCommand("DELETE FROM modellprognosen_testmode;", conn);
        cmd.ExecuteNonQuery();
        _cleared = true;
    }

    public void InsertTestForecast(
        DateTime datum,
        string modell,
        int vorhersageTag,
        decimal? tmkPrognose,
        decimal? sdkPrognose,
        decimal? rskPrognose)
    {
        using var conn = new SqlConnection(_connectionString);
        conn.Open();

        ClearTableIfNeeded(conn);

        using var cmd = new SqlCommand(@"
            INSERT INTO modellprognosen_testmode
                (Datum, Modell, VorhersageTag, TmkPrognose, SdkPrognose, RskPrognose, ErzeugtAm)
            VALUES
                (@Datum, @Modell, @VorhersageTag, @Tmk, @Sdk, @Rsk, SYSUTCDATETIME());
        ", conn);

        cmd.Parameters.Add("@Datum", SqlDbType.Date).Value = datum;
        cmd.Parameters.Add("@Modell", SqlDbType.NVarChar, 20).Value = modell;
        cmd.Parameters.Add("@VorhersageTag", SqlDbType.Int).Value = vorhersageTag;

        cmd.Parameters.Add("@Tmk", SqlDbType.Decimal).Value = (object?)tmkPrognose ?? DBNull.Value;
        cmd.Parameters.Add("@Sdk", SqlDbType.Decimal).Value = (object?)sdkPrognose ?? DBNull.Value;
        cmd.Parameters.Add("@Rsk", SqlDbType.Decimal).Value = (object?)rskPrognose ?? DBNull.Value;

        cmd.ExecuteNonQuery();
    }
}
