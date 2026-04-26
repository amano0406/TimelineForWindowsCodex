namespace TimelineForWindowsCodex.Web.Infrastructure;

public static class JobUrls
{
    public static string Details(string jobId) => $"/exports/{Uri.EscapeDataString(jobId)}";

    public static string Download(string jobId) => $"{Details(jobId)}/download";
}
