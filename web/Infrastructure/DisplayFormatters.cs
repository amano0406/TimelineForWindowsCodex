using System.Globalization;

namespace TimelineForWindowsCodex.Web.Infrastructure;

public static class DisplayFormatters
{
    public static string FormatDurationFriendly(double? seconds, Func<string, string> localize)
    {
        var totalSeconds = Math.Max(0, (int)Math.Round(seconds ?? 0, MidpointRounding.AwayFromZero));
        var hours = totalSeconds / 3600;
        var minutes = (totalSeconds % 3600) / 60;
        var remainSeconds = totalSeconds % 60;
        var parts = new List<string>();

        if (hours > 0)
        {
            parts.Add($"{hours}{localize("units.hour")}");
        }

        if (minutes > 0 || hours > 0)
        {
            parts.Add($"{minutes}{localize("units.min")}");
        }

        parts.Add($"{remainSeconds}{localize("units.sec")}");
        return string.Join(" ", parts);
    }

    public static string FormatFileSize(long valueBytes, Func<string, string> localize)
    {
        const double KiloByte = 1024d;
        const double MegaByte = KiloByte * 1024d;
        const double GigaByte = MegaByte * 1024d;

        var absoluteBytes = Math.Abs((double)valueBytes);
        return absoluteBytes switch
        {
            >= GigaByte => $"{FormatCompactNumber(valueBytes / GigaByte)} {localize("units.gb")}",
            >= MegaByte => $"{FormatCompactNumber(valueBytes / MegaByte)} {localize("units.mb")}",
            >= KiloByte => $"{FormatCompactNumber(valueBytes / KiloByte)} {localize("units.kb")}",
            _ => $"{valueBytes.ToString("0", CultureInfo.InvariantCulture)} {localize("units.byte")}",
        };
    }

    public static string FormatCreatedAt(string? value)
    {
        if (!DateTimeOffset.TryParse(value, out var parsed))
        {
            return "-";
        }

        return parsed.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.CurrentCulture);
    }

    public static double? CalculateElapsedSeconds(
        string? startedAt,
        string? completedAt = null,
        string? updatedAt = null)
    {
        if (!DateTimeOffset.TryParse(startedAt, out var started))
        {
            return null;
        }

        DateTimeOffset finishedAt;
        if (DateTimeOffset.TryParse(completedAt, out var completed))
        {
            finishedAt = completed;
        }
        else if (DateTimeOffset.TryParse(updatedAt, out var updated))
        {
            finishedAt = updated;
        }
        else
        {
            finishedAt = DateTimeOffset.Now;
        }

        return Math.Max(0, (finishedAt - started).TotalSeconds);
    }

    private static string FormatCompactNumber(double value)
    {
        var absoluteValue = Math.Abs(value);
        var format = absoluteValue >= 100 ? "0" : "0.#";
        return value.ToString(format, CultureInfo.InvariantCulture);
    }
}

