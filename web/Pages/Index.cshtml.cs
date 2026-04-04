using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace WindowsCodex2Timeline.Web.Pages;

public sealed class IndexModel : PageModel
{
    public IActionResult OnGet() => Redirect("/jobs/new");
}
