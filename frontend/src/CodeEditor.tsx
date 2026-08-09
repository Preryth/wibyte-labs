import Editor from "@monaco-editor/react";

type CodeEditorProps = {
  value: string;
  onChange: (value: string) => void;
  language?: string;
};

export default function CodeEditor({
  value,
  onChange,
  language = "python",
}: CodeEditorProps) {
  return (
    <Editor
      height="100%"
      defaultLanguage={language}
      value={value}
      onChange={(value) => onChange(value ?? "")}
      theme="vs-dark"
      options={{
        minimap: {
          enabled: false,
        },
        fontSize: 14,
        automaticLayout: true,
        padding: {
          top: 12,
        },
      }}
    />
  );
}
