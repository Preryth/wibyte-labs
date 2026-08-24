import {
  useEffect,
  useRef,
} from "react";

import Editor from "@monaco-editor/react";


type CodeEditorProps = {
  value: string;

  onChange: (
    value: string,
  ) => void;

  onActivity?: () => void;

  language?: string;
  readOnly?: boolean;
};


export default function CodeEditor({
  value,
  onChange,
  onActivity,
  language = "python",
  readOnly = false,
}: CodeEditorProps) {

  /*
   * Keep the latest activity callback
   * without recreating the editor.
   */

  const onActivityRef =
    useRef<
      (() => void) | undefined
    >(onActivity);


  useEffect(() => {
    onActivityRef.current =
      onActivity;
  }, [onActivity]);


  /*
   * Monaco can call onChange for
   * every edit.
   *
   * We only use this to update the
   * editor content immediately and
   * notify the activity system.
   */

  function handleChange(
    value: string | undefined,
  ) {
    onChange(
      value ?? "",
    );

    onActivityRef.current?.();
  }


  return (
    <Editor
      height="100%"
      defaultLanguage={language}
      value={value}
      onChange={handleChange}
      theme="vs-dark"
      options={{
        minimap: {
          enabled: false,
        },

        fontSize: 14,

        automaticLayout: true,

        readOnly,

        padding: {
          top: 12,
        },
      }}
    />
  );
}