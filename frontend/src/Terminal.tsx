import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";

import "@xterm/xterm/css/xterm.css";

type TerminalProps = {
  labId: string;
};

type TerminalMessage =
  | {
      type: "output";
      data: string;
    }
  | {
      type: "error";
      message: string;
    };

export default function Terminal({ labId }: TerminalProps) {
  const terminalElementRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!terminalElementRef.current) {
      return;
    }

    const terminal = new XTerm({
      cursorBlink: true,
      fontSize: 14,
      convertEol: true,
    });

    const fitAddon = new FitAddon();

    terminal.loadAddon(fitAddon);
    terminal.open(terminalElementRef.current);
    fitAddon.fit();

    const websocket = new WebSocket(
      `ws://127.0.0.1:8000/labs/${labId}/terminal`,
    );

    websocket.onopen = () => {
      terminal.write("\r\nConnected to WPL terminal.\r\n");
    };

    websocket.onmessage = (event) => {
      const message: TerminalMessage = JSON.parse(event.data);

      if (message.type === "output") {
        terminal.write(message.data);
      }

      if (message.type === "error") {
        terminal.write(`\r\nError: ${message.message}\r\n`);
      }
    };

    websocket.onerror = () => {
      terminal.write("\r\nWebSocket error.\r\n");
    };

    websocket.onclose = () => {
      terminal.write("\r\n\r\nTerminal connection closed.\r\n");
    };

    const dataDisposable = terminal.onData((data) => {
      if (websocket.readyState === WebSocket.OPEN) {
        websocket.send(
          JSON.stringify({
            type: "input",
            data,
          }),
        );
      }
    });

    const handleResize = () => {
      fitAddon.fit();
    };

    window.addEventListener("resize", handleResize);

    return () => {
      dataDisposable.dispose();
      window.removeEventListener("resize", handleResize);

      websocket.close();
      terminal.dispose();
    };
  }, [labId]);

  return (
    <div
      ref={terminalElementRef}
      style={{
        width: "100%",
        height: "500px",
      }}
    />
  );
}