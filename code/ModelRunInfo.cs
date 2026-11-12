using System;
using System.Collections.Generic;

public class TempSeriesResult
{
    public List<int> Days { get; set; } = new();
    public List<double> CumMeans { get; set; } = new();
    public Dictionary<int, double> DayMeans { get; set; } = new();
}

public class RainSeriesResult
{
    public double[] Days { get; set; } = Array.Empty<double>();
    public double[] Values { get; set; } = Array.Empty<double>();
}

public class ModelRunInfo
{
    public string ModelName { get; set; } = "";
    public DateTime RunTimeUtc { get; set; }
    public string RunString => $"{ModelName}: Modelllauf {RunTimeUtc:dd.MM.yyyy HH:mm} UTC";
}

public class ForecastData
{
    public TempSeriesResult IconTemp { get; set; } = new();
    public TempSeriesResult GfsTemp { get; set; } = new();

    public RainSeriesResult IconRain { get; set; } = new();
    public RainSeriesResult GfsRain { get; set; } = new();
}
