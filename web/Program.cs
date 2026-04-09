using System.Globalization;
using TimelineForWindowsCodex.Web.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorPages();
builder.Services.AddSingleton<AppPaths>();
builder.Services.AddSingleton<LanguageService>();
builder.Services.AddSingleton<JsonLocalizationService>();
builder.Services.AddSingleton<SettingsStore>();
builder.Services.AddSingleton<CodexDiscoveryService>();
builder.Services.AddSingleton<RunStore>();

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.UseDeveloperExceptionPage();
}
else
{
    app.UseExceptionHandler("/Error");
}

app.UseRouting();
app.Use(async (context, next) =>
{
    var languageService = context.RequestServices.GetRequiredService<LanguageService>();
    var lang = languageService.Resolve(context.Request);
    var culture = string.Equals(lang, "ja", StringComparison.OrdinalIgnoreCase)
        ? new CultureInfo("ja-JP")
        : new CultureInfo("en-US");

    CultureInfo.CurrentCulture = culture;
    CultureInfo.CurrentUICulture = culture;
    await next();
});
app.UseAuthorization();

app.MapStaticAssets();
app.MapRazorPages()
    .WithStaticAssets();

app.MapGet("/api/app/version", () => Results.Ok(new
{
    instance_id = app.Services.GetRequiredService<AppPaths>().InstanceId,
}));

app.MapGet("/jobs/{id}/download", async (string id, RunStore runStore, CancellationToken cancellationToken) =>
{
    var archivePath = await runStore.GetArchivePathAsync(id, cancellationToken);
    if (archivePath is null || !File.Exists(archivePath))
    {
        return Results.NotFound();
    }

    return Results.File(
        archivePath,
        contentType: "application/zip",
        fileDownloadName: Path.GetFileName(archivePath));
});

app.Run();
