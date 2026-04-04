using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using WindowsCodex2Timeline.Web.Services;

namespace WindowsCodex2Timeline.Web.Pages;

public sealed class SettingsModel(
    SettingsStore settingsStore,
    LanguageService languageService,
    JsonLocalizationService localizer) : PageModel
{
    [BindProperty]
    public string DefaultPrimaryCodexHomePath { get; set; } = string.Empty;

    [BindProperty]
    public string DefaultBackupCodexHomePathsText { get; set; } = string.Empty;

    [BindProperty]
    public string DefaultEnrichmentRootPathsText { get; set; } = string.Empty;

    [BindProperty]
    public bool DefaultIncludeArchivedSources { get; set; }

    [BindProperty]
    public bool DefaultIncludeToolOutputs { get; set; }

    [BindProperty]
    public string DefaultRedactionProfile { get; set; } = "strict";

    [BindProperty]
    public string UiLanguage { get; set; } = "ja";

    [TempData]
    public string? StatusMessage { get; set; }

    public IReadOnlyList<SupportedLanguage> SupportedLanguages { get; private set; } = [];

    public async Task OnGetAsync(CancellationToken cancellationToken)
    {
        await LoadAsync(cancellationToken);
    }

    public async Task<IActionResult> OnPostAsync(CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(DefaultPrimaryCodexHomePath))
        {
            ModelState.AddModelError(string.Empty, L("error.primary_root_required"));
            SupportedLanguages = languageService.GetSupportedLanguages();
            return Page();
        }

        await settingsStore.SaveAsync(
            new Models.AppSettingsDocument
            {
                DefaultPrimaryCodexHomePath = DefaultPrimaryCodexHomePath.Trim(),
                DefaultBackupCodexHomePaths = ParseLines(DefaultBackupCodexHomePathsText),
                DefaultEnrichmentRootPaths = ParseLines(DefaultEnrichmentRootPathsText),
                DefaultIncludeArchivedSources = DefaultIncludeArchivedSources,
                DefaultIncludeToolOutputs = DefaultIncludeToolOutputs,
                DefaultRedactionProfile = string.Equals(DefaultRedactionProfile, "loose", StringComparison.OrdinalIgnoreCase)
                    ? "loose"
                    : "strict",
                UiLanguage = UiLanguage,
            },
            cancellationToken);

        StatusMessage = localizer.Get(UiLanguage, "status.settings_saved");
        return RedirectToPage(new { lang = UiLanguage });
    }

    private async Task LoadAsync(CancellationToken cancellationToken)
    {
        var settings = await settingsStore.LoadAsync(cancellationToken);
        DefaultPrimaryCodexHomePath = settings.DefaultPrimaryCodexHomePath;
        DefaultBackupCodexHomePathsText = string.Join(Environment.NewLine, settings.DefaultBackupCodexHomePaths);
        DefaultEnrichmentRootPathsText = string.Join(Environment.NewLine, settings.DefaultEnrichmentRootPaths);
        DefaultIncludeArchivedSources = settings.DefaultIncludeArchivedSources;
        DefaultIncludeToolOutputs = settings.DefaultIncludeToolOutputs;
        DefaultRedactionProfile = settings.DefaultRedactionProfile;
        UiLanguage = settings.UiLanguage;
        SupportedLanguages = languageService.GetSupportedLanguages();
    }

    private string CurrentLang() => languageService.Resolve(Request);

    private string L(string key) => localizer.Get(CurrentLang(), key);

    private static List<string> ParseLines(string? raw) =>
        (raw ?? string.Empty)
        .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
        .Where(static item => !string.IsNullOrWhiteSpace(item))
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .ToList();
}
