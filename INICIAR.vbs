Option Explicit

Dim shell, fso, base, pythonw, app, url, port, edge, chrome, iexplore
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

base = fso.GetParentFolderName(WScript.ScriptFullName)
port = "47891"
url = "http://127.0.0.1:" & port
pythonw = base & "\.venv\Scripts\pythonw.exe"
app = base & "\app.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "O sistema ainda não foi instalado neste computador." & vbCrLf & vbCrLf & _
           "Execute INSTALAR.bat uma vez.", 48, "ALT Gestão de Condomínios"
    WScript.Quit 1
End If

' Não inicia uma segunda cópia se o servidor já estiver rodando.
If Not ServerReady(url) Then
    shell.Environment("Process")("ALT_PORT") = port
    shell.Run """" & pythonw & """ """ & app & """", 0, False
    If Not WaitForServer(url, 15) Then
        MsgBox "Não foi possível iniciar o sistema ALT." & vbCrLf & vbCrLf & _
               "Verifique se a instalação foi concluída corretamente.", 16, "ALT Gestão de Condomínios"
        WScript.Quit 2
    End If
End If

' Edge/Chrome em modo aplicativo deixa o sistema com aparência de programa.
edge = shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Microsoft\Edge\Application\msedge.exe"
If Not fso.FileExists(edge) Then edge = shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Microsoft\Edge\Application\msedge.exe"
chrome = shell.ExpandEnvironmentStrings("%ProgramFiles%") & "\Google\Chrome\Application\chrome.exe"
If Not fso.FileExists(chrome) Then chrome = shell.ExpandEnvironmentStrings("%ProgramFiles(x86)%") & "\Google\Chrome\Application\chrome.exe"

If fso.FileExists(edge) Then
    shell.Run """" & edge & """ --app=""" & url & """", 1, False
ElseIf fso.FileExists(chrome) Then
    shell.Run """" & chrome & """ --app=""" & url & """", 1, False
Else
    shell.Run url, 1, False
End If

Set fso = Nothing
Set shell = Nothing
WScript.Quit 0

Function ServerReady(target)
    Dim http
    On Error Resume Next
    Set http = CreateObject("MSXML2.XMLHTTP.6.0")
    http.Open "GET", target & "/health", False
    http.setRequestHeader "Cache-Control", "no-cache"
    http.Send
    ServerReady = (Err.Number = 0 And http.Status = 200 And InStr(1, http.ResponseText, "ALT", vbTextCompare) > 0)
    Err.Clear
    Set http = Nothing
    On Error GoTo 0
End Function

Function WaitForServer(target, seconds)
    Dim i
    For i = 1 To seconds * 2
        WScript.Sleep 500
        If ServerReady(target) Then
            WaitForServer = True
            Exit Function
        End If
    Next
    WaitForServer = False
End Function
