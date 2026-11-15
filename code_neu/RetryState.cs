public class RetryState
{
    public string RunId { get; set; } = "";

    public bool Finished { get; set; }

    public int Attempt { get; set; }

    public DateTime LastUpdateUtc { get; set; }
}
