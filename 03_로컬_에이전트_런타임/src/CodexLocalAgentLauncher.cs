using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;
            string packageRoot = ResolvePackageRoot(baseDir);
            string scriptPath = Path.Combine(packageRoot, "scripts", "invoke_agent_orchestrator.ps1");

            if (!File.Exists(scriptPath))
            {
                Console.Error.WriteLine("Launcher script was not found: " + scriptPath);
                return 2;
            }

            if (args.Length == 0)
            {
                PrintUsage(scriptPath);
                return 1;
            }

            var psi = new ProcessStartInfo
            {
                FileName = "powershell.exe",
                UseShellExecute = false,
                RedirectStandardOutput = false,
                RedirectStandardError = false,
                CreateNoWindow = false,
                WorkingDirectory = packageRoot,
                Arguments = BuildPowerShellArguments(scriptPath, args)
            };

            using (var process = Process.Start(psi))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.Message);
            return 10;
        }
    }

    private static string ResolvePackageRoot(string baseDir)
    {
        string trimmed = baseDir.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        var current = new DirectoryInfo(trimmed);
        if (current.Name.Equals("bin", StringComparison.OrdinalIgnoreCase) && current.Parent != null)
        {
            return current.Parent.FullName;
        }
        return current.FullName;
    }

    private static string BuildPowerShellArguments(string scriptPath, string[] args)
    {
        var builder = new StringBuilder();
        builder.Append("-NoProfile -ExecutionPolicy Bypass -File ");
        builder.Append(Quote(scriptPath));
        foreach (string arg in args)
        {
            builder.Append(' ');
            builder.Append(Quote(arg));
        }
        return builder.ToString();
    }

    private static string Quote(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "\"\"";
        }

        if (!value.Any(ch => char.IsWhiteSpace(ch) || ch == '"' || ch == '\\'))
        {
            return value;
        }

        var builder = new StringBuilder();
        builder.Append('"');
        int backslashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\')
            {
                backslashes++;
                continue;
            }

            if (ch == '"')
            {
                builder.Append('\\', backslashes * 2 + 1);
                builder.Append('"');
                backslashes = 0;
                continue;
            }

            if (backslashes > 0)
            {
                builder.Append('\\', backslashes);
                backslashes = 0;
            }

            builder.Append(ch);
        }

        if (backslashes > 0)
        {
            builder.Append('\\', backslashes * 2);
        }

        builder.Append('"');
        return builder.ToString();
    }

    private static void PrintUsage(string scriptPath)
    {
        Console.WriteLine("Codex Local Agent Launcher");
        Console.WriteLine("Backed by: " + scriptPath);
        Console.WriteLine();
        Console.WriteLine("Examples:");
        Console.WriteLine("  CodexLocalAgentLauncher.exe -Mode status");
        Console.WriteLine("  CodexLocalAgentLauncher.exe -Mode route -TaskText \"Current Chrome selector changed. Rebuild the guide.\"");
        Console.WriteLine("  CodexLocalAgentLauncher.exe -Mode new-chat -Provider gemini");
        Console.WriteLine("  CodexLocalAgentLauncher.exe -Mode consult -TaskText \"Compare a high-risk automation design.\" -Send");
    }
}
