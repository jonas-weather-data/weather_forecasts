using System.Collections.Generic;

public class ModelRunStatus
{
    public string ModelName { get; set; } = "";

    public bool Complete { get; set; }

    public int ExpectedHours { get; set; }

    public int AvailableHours { get; set; }

    public string? ErrorMessage { get; set; }
}

public class ForecastStatus
{
    public bool AllDataAvailable { get; set; }

    public bool FinalAttempt { get; set; }

    public int AvailableHours { get; set; }

    public int ExpectedHours { get; set; }

    public double PercentAvailable { get; set; }

    public List<string> MissingModels { get; set; } = new();

    public List<ModelRunStatus> ModelStatuses { get; set; } = new();
}
