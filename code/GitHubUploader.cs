using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

public class GitHubUploader
{
    private readonly string _token;
    private readonly string _owner;
    private readonly string _repo;
    private readonly HttpClient _client;

    public GitHubUploader(string owner, string repo)
    {
        _token = Environment.GetEnvironmentVariable("GITHUB_TOKEN");
        if (string.IsNullOrWhiteSpace(_token))
            throw new Exception("GITHUB_TOKEN ist nicht gesetzt oder leer.");

        _owner = owner;
        _repo = repo;

        _client = new HttpClient();
        _client.DefaultRequestHeaders.UserAgent.ParseAdd("WeatherUploader");
        _client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("token", _token);
    }

    // ---------------------------------------------------------
    // GENERISCHE UPLOAD-LOGIK
    // ---------------------------------------------------------
    private async Task<string> UploadInternalAsync(string repoPath, string localFilePath, string commitMessage, bool overwrite)
    {
        string apiUrl = $"https://api.github.com/repos/{_owner}/{_repo}/contents/{repoPath}";

        byte[] bytes = System.IO.File.ReadAllBytes(localFilePath);
        string base64 = Convert.ToBase64String(bytes);

        string? sha = await TryGetShaAsync(apiUrl);

        if (!overwrite && sha != null)
        {
            var metaResp = await _client.GetAsync(apiUrl);
            string metaJson = await metaResp.Content.ReadAsStringAsync();
            using var metaDoc = JsonDocument.Parse(metaJson);

            return metaDoc.RootElement.GetProperty("download_url").GetString();
        }

        var body = new Dictionary<string, object>
        {
            ["message"] = commitMessage,
            ["content"] = base64
        };

        if (sha != null)
            body["sha"] = sha;

        string jsonBody = JsonSerializer.Serialize(body);
        var content = new StringContent(jsonBody, Encoding.UTF8, "application/json");

        var response = await _client.PutAsync(apiUrl, content);
        string json = await response.Content.ReadAsStringAsync();

        if (!response.IsSuccessStatusCode)
        {
            string requestId = response.Headers.Contains("X-GitHub-Request-Id")
                ? string.Join(",", response.Headers.GetValues("X-GitHub-Request-Id"))
                : "unbekannt";

            throw new Exception(
                $"GitHub PUT-Fehler\n" +
                $"Status: {response.StatusCode}\n" +
                $"Pfad: {repoPath}\n" +
                $"Dateigröße: {bytes.Length} Bytes\n" +
                $"SHA vorhanden: {sha != null}\n" +
                $"Request-ID: {requestId}\n" +
                $"Antwort: {json}");
        }

        using var doc = JsonDocument.Parse(json);

        return doc.RootElement
            .GetProperty("content")
            .GetProperty("download_url")
            .GetString();

        return doc.RootElement.GetProperty("content").GetProperty("download_url").GetString();
    }

    private async Task<string?> TryGetShaAsync(string apiUrl)
    {
        var response = await _client.GetAsync(apiUrl);
        string json = await response.Content.ReadAsStringAsync();

        if (response.StatusCode == HttpStatusCode.NotFound)
            return null;

        if (!response.IsSuccessStatusCode)
        {
            throw new Exception(
                $"GitHub GET-Fehler: {response.StatusCode}\n" +
                $"URL: {apiUrl}\n" +
                $"Antwort: {json}");
        }

        using var doc = JsonDocument.Parse(json);

        if (doc.RootElement.TryGetProperty("sha", out var shaProp))
            return shaProp.GetString();

        throw new Exception("GitHub-Antwort enthält keinen SHA-Hash.");
    }    

    // ---------------------------------------------------------
    // ALTE METHODEN (BLEIBEN)
    // ---------------------------------------------------------

    public Task<string> UploadFileAsync(string localFilePath, string fileName)
    {
        string dateFolder = DateTime.Now.ToString("yyyy-MM-dd");
        string repoPath = $"images/{dateFolder}/{fileName}";
        return UploadInternalAsync(repoPath, localFilePath, $"Upload {fileName}", overwrite: false);
    }

    public Task<string> UploadLatestAsync(string localFilePath, string fileName)
    {
        string repoPath = $"images/latest/{fileName}";
        return UploadInternalAsync(repoPath, localFilePath, $"Update latest {fileName}", overwrite: true);
    }

    // ---------------------------------------------------------
    // NEUE METHODEN FÜR 00z / 06z / 12z
    // ---------------------------------------------------------

    public Task<string> UploadRunLatestAsync(string run, string localFilePath, string fileName)
    {
        string repoPath = $"images/{run}/latest/{fileName}";
        return UploadInternalAsync(repoPath, localFilePath, $"Update {run}/latest {fileName}", overwrite: true);
    }

    public Task<string> UploadRunDayAsync(string run, string dateFolder, string localFilePath, string fileName)
    {
        string repoPath = $"images/{run}/{dateFolder}/{fileName}";
        return UploadInternalAsync(repoPath, localFilePath, $"Upload {run}/{dateFolder} {fileName}", overwrite: true);
    }
}
