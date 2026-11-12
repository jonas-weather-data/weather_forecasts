using System;
using System.IO;
using System.Threading.Tasks;

public class GitHubUploader
{
    private readonly string _owner;
    private readonly string _repo;
    private readonly string _repoRoot;

    public GitHubUploader(string owner, string repo)
    {
        _owner = owner;
        _repo = repo;
        _repoRoot = Environment.GetEnvironmentVariable("GITHUB_WORKSPACE")
                    ?? FindRepoRoot(Directory.GetCurrentDirectory());
    }

    private string FindRepoRoot(string startDir)
    {
        var dir = new DirectoryInfo(startDir);
        while (dir != null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, ".git")))
                return dir.FullName;
            dir = dir.Parent;
        }
        return Directory.GetCurrentDirectory();
    }

    private Task<string> SaveToLatestAsync(string repoPath, string localFilePath)
    {
        string targetPath = Path.Combine(_repoRoot, repoPath.Replace('/', Path.DirectorySeparatorChar));
        string? targetDir = Path.GetDirectoryName(targetPath);

        if (!string.IsNullOrEmpty(targetDir))
            Directory.CreateDirectory(targetDir);

        string fullSource = Path.GetFullPath(localFilePath);
        string fullTarget = Path.GetFullPath(targetPath);

        if (!string.Equals(fullSource, fullTarget, StringComparison.OrdinalIgnoreCase))
        {
            File.Copy(fullSource, fullTarget, overwrite: true);
        }

        string rawUrl = $"https://githubusercontent.com{_owner}/{_repo}/main/{repoPath}";
        return Task.FromResult(rawUrl);
    }

    // ---------------------------------------------------------
    // DATUMSORDNER DEAKTIVIERT (macht nichts mehr)
    // ---------------------------------------------------------

    public Task<string> UploadFileAsync(string localFilePath, string fileName)
    {
        return Task.FromResult(string.Empty);
    }

    public Task<string> UploadRunDayAsync(string run, string dateFolder, string localFilePath, string fileName)
    {
        return Task.FromResult(string.Empty);
    }

    // ---------------------------------------------------------
    // NUR NOCH LATEST-ORDNER ÜBERSCHREIBEN
    // ---------------------------------------------------------

    public Task<string> UploadLatestAsync(string localFilePath, string fileName)
    {
        string repoPath = $"images/latest/{fileName}";
        return SaveToLatestAsync(repoPath, localFilePath);
    }

    public Task<string> UploadRunLatestAsync(string run, string localFilePath, string fileName)
    {
        string repoPath = $"images/{run}/latest/{fileName}";
        return SaveToLatestAsync(repoPath, localFilePath);
    }
}
