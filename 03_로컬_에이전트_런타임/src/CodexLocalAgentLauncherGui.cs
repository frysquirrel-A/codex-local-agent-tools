using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class CodexLocalAgentLauncherGuiProgram
{
    [STAThread]
    private static void Main()
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LauncherForm());
    }
}

internal sealed class LauncherForm : Form
{
    private readonly string _packageRoot;
    private readonly string _scriptPath;
    private readonly TextBox _taskTextBox;
    private readonly TextBox _promptTextBox;
    private readonly ComboBox _providerComboBox;
    private readonly CheckBox _sendCheckBox;
    private readonly NumericUpDown _intervalInput;
    private readonly TextBox _outputTextBox;
    private readonly Label _statusLabel;
    private readonly Button[] _actionButtons;

    public LauncherForm()
    {
        _packageRoot = ResolvePackageRoot(AppDomain.CurrentDomain.BaseDirectory);
        _scriptPath = Path.Combine(_packageRoot, "scripts", "invoke_agent_orchestrator.ps1");

        Text = "Codex Local Agent Launcher GUI";
        StartPosition = FormStartPosition.CenterScreen;
        MinimumSize = new Size(980, 760);
        Size = new Size(1200, 860);
        Font = new Font("Malgun Gothic", 9F, FontStyle.Regular, GraphicsUnit.Point);

        var root = new TableLayoutPanel();
        root.Dock = DockStyle.Fill;
        root.ColumnCount = 1;
        root.RowCount = 6;
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 108F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 88F));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
        Controls.Add(root);

        var introPanel = new Panel();
        introPanel.Dock = DockStyle.Fill;
        introPanel.Padding = new Padding(12, 12, 12, 4);
        introPanel.Height = 72;

        var titleLabel = new Label();
        titleLabel.AutoSize = true;
        titleLabel.Font = new Font(Font, FontStyle.Bold);
        titleLabel.Text = "Codex Local Agent Launcher";
        titleLabel.Location = new Point(0, 0);
        introPanel.Controls.Add(titleLabel);

        var summaryLabel = new Label();
        summaryLabel.AutoSize = true;
        summaryLabel.MaximumSize = new Size(1120, 0);
        summaryLabel.Text =
            "더블클릭 후 status, route, consult, new-chat, watch-start, watch-stop를 버튼으로 실행합니다. " +
            "현재 런타임 폴더와 invoke_agent_orchestrator.ps1를 직접 호출합니다.";
        summaryLabel.Location = new Point(0, 28);
        introPanel.Controls.Add(summaryLabel);

        root.Controls.Add(introPanel, 0, 0);

        var taskGroup = new GroupBox();
        taskGroup.Dock = DockStyle.Fill;
        taskGroup.Padding = new Padding(12, 14, 12, 12);
        taskGroup.Text = "Task Text";
        _taskTextBox = new TextBox();
        _taskTextBox.Dock = DockStyle.Fill;
        _taskTextBox.Multiline = true;
        _taskTextBox.ScrollBars = ScrollBars.Vertical;
        _taskTextBox.Text =
            "같은 보고서를 이어서 다듬고 코드 설명을 보강해줘.";
        taskGroup.Controls.Add(_taskTextBox);
        root.Controls.Add(taskGroup, 0, 1);

        var promptGroup = new GroupBox();
        promptGroup.Dock = DockStyle.Fill;
        promptGroup.Padding = new Padding(12, 14, 12, 12);
        promptGroup.Text = "Prompt Override (Consult 전용, 비워두면 Task Text 사용)";
        _promptTextBox = new TextBox();
        _promptTextBox.Dock = DockStyle.Fill;
        _promptTextBox.Multiline = true;
        _promptTextBox.ScrollBars = ScrollBars.Vertical;
        promptGroup.Controls.Add(_promptTextBox);
        root.Controls.Add(promptGroup, 0, 2);

        var optionsPanel = new FlowLayoutPanel();
        optionsPanel.Dock = DockStyle.Fill;
        optionsPanel.AutoSize = true;
        optionsPanel.WrapContents = true;
        optionsPanel.Padding = new Padding(12, 6, 12, 6);

        var providerLabel = new Label();
        providerLabel.AutoSize = true;
        providerLabel.Text = "Consult Provider";
        providerLabel.Margin = new Padding(0, 8, 8, 0);
        optionsPanel.Controls.Add(providerLabel);

        _providerComboBox = new ComboBox();
        _providerComboBox.DropDownStyle = ComboBoxStyle.DropDownList;
        _providerComboBox.Width = 160;
        _providerComboBox.Items.AddRange(new object[]
        {
            "Auto (policy)",
            "gemini",
            "chatgpt"
        });
        _providerComboBox.SelectedIndex = 0;
        _providerComboBox.Margin = new Padding(0, 3, 16, 0);
        optionsPanel.Controls.Add(_providerComboBox);

        _sendCheckBox = new CheckBox();
        _sendCheckBox.AutoSize = true;
        _sendCheckBox.Text = "Consult 시 바로 전송";
        _sendCheckBox.Margin = new Padding(0, 6, 16, 0);
        optionsPanel.Controls.Add(_sendCheckBox);

        var intervalLabel = new Label();
        intervalLabel.AutoSize = true;
        intervalLabel.Text = "Watch Interval (sec)";
        intervalLabel.Margin = new Padding(0, 8, 8, 0);
        optionsPanel.Controls.Add(intervalLabel);

        _intervalInput = new NumericUpDown();
        _intervalInput.DecimalPlaces = 1;
        _intervalInput.Minimum = 0.1M;
        _intervalInput.Maximum = 10.0M;
        _intervalInput.Increment = 0.1M;
        _intervalInput.Value = 0.1M;
        _intervalInput.Width = 80;
        _intervalInput.Margin = new Padding(0, 3, 16, 0);
        optionsPanel.Controls.Add(_intervalInput);

        _statusLabel = new Label();
        _statusLabel.AutoSize = true;
        _statusLabel.Text = "대기 중";
        _statusLabel.Margin = new Padding(0, 8, 0, 0);
        optionsPanel.Controls.Add(_statusLabel);

        root.Controls.Add(optionsPanel, 0, 3);

        var actionPanel = new FlowLayoutPanel();
        actionPanel.Dock = DockStyle.Fill;
        actionPanel.AutoSize = true;
        actionPanel.WrapContents = true;
        actionPanel.Padding = new Padding(12, 0, 12, 8);

        var statusButton = CreateActionButton("Status", async delegate { await ExecuteAsync("Status", new[] { "-Mode", "status" }); });
        var routeButton = CreateActionButton("Route", async delegate
        {
            if (!EnsureTaskText()) return;
            await ExecuteAsync("Route", new[] { "-Mode", "route", "-TaskText", _taskTextBox.Text.Trim() });
        });
        var consultButton = CreateActionButton("Consult", async delegate
        {
            if (!EnsureTaskText()) return;
            var arguments = new List<string>
            {
                "-Mode", "consult",
                "-TaskText", _taskTextBox.Text.Trim()
            };

            string provider = GetSelectedProvider();
            if (!string.IsNullOrEmpty(provider))
            {
                arguments.Add("-Provider");
                arguments.Add(provider);
            }

            string prompt = _promptTextBox.Text.Trim();
            if (!string.IsNullOrWhiteSpace(prompt))
            {
                arguments.Add("-Prompt");
                arguments.Add(prompt);
            }

            if (_sendCheckBox.Checked)
            {
                arguments.Add("-Send");
            }

            await ExecuteAsync("Consult", arguments.ToArray());
        });
        var newGeminiButton = CreateActionButton("New Gemini Chat", async delegate
        {
            await ExecuteAsync("New Gemini Chat", new[] { "-Mode", "new-chat", "-Provider", "gemini" });
        });
        var newChatGptButton = CreateActionButton("New ChatGPT Chat", async delegate
        {
            await ExecuteAsync("New ChatGPT Chat", new[] { "-Mode", "new-chat", "-Provider", "chatgpt" });
        });
        var watchStartButton = CreateActionButton("Watch Start", async delegate
        {
            string value = _intervalInput.Value.ToString("0.0", CultureInfo.InvariantCulture);
            await ExecuteAsync("Watch Start", new[] { "-Mode", "watch-start", "-IntervalSeconds", value });
        });
        var watchStopButton = CreateActionButton("Watch Stop", async delegate
        {
            await ExecuteAsync("Watch Stop", new[] { "-Mode", "watch-stop" });
        });
        var openFolderButton = CreateActionButton("Open Runtime Folder", delegate
        {
            Process.Start("explorer.exe", _packageRoot);
            AppendOutputLine("런타임 폴더를 열었습니다: " + _packageRoot);
        });
        var clearOutputButton = CreateActionButton("Clear Output", delegate
        {
            _outputTextBox.Clear();
            _statusLabel.Text = "출력 초기화";
        });
        var copyOutputButton = CreateActionButton("Copy Output", delegate
        {
            if (!string.IsNullOrWhiteSpace(_outputTextBox.Text))
            {
                Clipboard.SetText(_outputTextBox.Text);
                _statusLabel.Text = "출력을 클립보드에 복사했습니다.";
            }
        });

        _actionButtons = new[]
        {
            statusButton,
            routeButton,
            consultButton,
            newGeminiButton,
            newChatGptButton,
            watchStartButton,
            watchStopButton,
            openFolderButton,
            clearOutputButton,
            copyOutputButton
        };

        foreach (var button in _actionButtons)
        {
            actionPanel.Controls.Add(button);
        }

        root.Controls.Add(actionPanel, 0, 4);

        var outputGroup = new GroupBox();
        outputGroup.Dock = DockStyle.Fill;
        outputGroup.Padding = new Padding(12, 14, 12, 12);
        outputGroup.Text = "Output";
        _outputTextBox = new TextBox();
        _outputTextBox.Dock = DockStyle.Fill;
        _outputTextBox.Multiline = true;
        _outputTextBox.ScrollBars = ScrollBars.Both;
        _outputTextBox.WordWrap = false;
        _outputTextBox.ReadOnly = true;
        _outputTextBox.Font = new Font("Consolas", 9F, FontStyle.Regular, GraphicsUnit.Point);
        outputGroup.Controls.Add(_outputTextBox);
        root.Controls.Add(outputGroup, 0, 5);

        AppendOutputLine("GUI 런처 준비 완료");
        AppendOutputLine("Package Root: " + _packageRoot);
        AppendOutputLine("Script Path : " + _scriptPath);
    }

    private Button CreateActionButton(string text, Func<Task> action)
    {
        var button = new Button();
        button.AutoSize = true;
        button.Text = text;
        button.Padding = new Padding(8, 4, 8, 4);
        button.Margin = new Padding(0, 0, 8, 8);
        button.Click += async delegate { await action(); };
        return button;
    }

    private Button CreateActionButton(string text, Action action)
    {
        var button = new Button();
        button.AutoSize = true;
        button.Text = text;
        button.Padding = new Padding(8, 4, 8, 4);
        button.Margin = new Padding(0, 0, 8, 8);
        button.Click += delegate { action(); };
        return button;
    }

    private async Task ExecuteAsync(string title, string[] args)
    {
        if (!File.Exists(_scriptPath))
        {
            MessageBox.Show("오케스트레이터 스크립트를 찾지 못했습니다.\r\n" + _scriptPath, "Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        SetBusy(true, title + " 실행 중...");
        AppendOutputSeparator();
        AppendOutputLine("> " + title);
        AppendOutputLine("Args: " + string.Join(" ", args));

        try
        {
            InvocationResult result = await Task.Run(delegate { return InvokeOrchestrator(args); });
            if (!string.IsNullOrWhiteSpace(result.StandardOutput))
            {
                AppendOutputLine(result.StandardOutput.TrimEnd());
            }
            if (!string.IsNullOrWhiteSpace(result.StandardError))
            {
                AppendOutputLine("[stderr]");
                AppendOutputLine(result.StandardError.TrimEnd());
            }

            _statusLabel.Text = result.ExitCode == 0
                ? title + " 완료"
                : title + " 실패 (exit " + result.ExitCode.ToString(CultureInfo.InvariantCulture) + ")";
        }
        catch (Exception ex)
        {
            AppendOutputLine("[launcher error]");
            AppendOutputLine(ex.Message);
            _statusLabel.Text = title + " 예외 발생";
            MessageBox.Show(ex.Message, "Launcher Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            SetBusy(false, _statusLabel.Text);
        }
    }

    private InvocationResult InvokeOrchestrator(string[] args)
    {
        var psi = new ProcessStartInfo
        {
            FileName = "powershell.exe",
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = _packageRoot,
            Arguments = BuildPowerShellArguments(_scriptPath, args)
        };

        using (var process = Process.Start(psi))
        {
            if (process == null)
            {
                throw new InvalidOperationException("powershell.exe could not be started.");
            }

            string stdout = process.StandardOutput.ReadToEnd();
            string stderr = process.StandardError.ReadToEnd();
            process.WaitForExit();

            return new InvocationResult(process.ExitCode, stdout, stderr);
        }
    }

    private void SetBusy(bool isBusy, string statusText)
    {
        foreach (var button in _actionButtons)
        {
            button.Enabled = !isBusy;
        }

        _statusLabel.Text = statusText;
        UseWaitCursor = isBusy;
    }

    private bool EnsureTaskText()
    {
        if (!string.IsNullOrWhiteSpace(_taskTextBox.Text))
        {
            return true;
        }

        MessageBox.Show("Task Text를 먼저 입력해 주세요.", "Task Text Required", MessageBoxButtons.OK, MessageBoxIcon.Information);
        return false;
    }

    private string GetSelectedProvider()
    {
        if (_providerComboBox.SelectedItem == null)
        {
            return null;
        }

        string value = _providerComboBox.SelectedItem.ToString();
        if (value == "gemini" || value == "chatgpt")
        {
            return value;
        }

        return null;
    }

    private void AppendOutputSeparator()
    {
        AppendOutputLine(string.Empty);
        AppendOutputLine(new string('=', 72));
    }

    private void AppendOutputLine(string text)
    {
        string prefix = "[" + DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture) + "] ";
        if (string.IsNullOrEmpty(_outputTextBox.Text))
        {
            _outputTextBox.Text = prefix + text;
        }
        else
        {
            _outputTextBox.AppendText(Environment.NewLine + prefix + text);
        }

        _outputTextBox.SelectionStart = _outputTextBox.TextLength;
        _outputTextBox.ScrollToCaret();
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

    private sealed class InvocationResult
    {
        public InvocationResult(int exitCode, string standardOutput, string standardError)
        {
            ExitCode = exitCode;
            StandardOutput = standardOutput ?? string.Empty;
            StandardError = standardError ?? string.Empty;
        }

        public int ExitCode { get; private set; }
        public string StandardOutput { get; private set; }
        public string StandardError { get; private set; }
    }
}
