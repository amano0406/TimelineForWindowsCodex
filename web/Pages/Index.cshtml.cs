using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace TimelineForWindowsCodex.Web.Pages;

public sealed class IndexModel : PageModel
{
    public IActionResult OnGet() => Redirect("/jobs/new");
}
