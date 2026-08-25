import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";

import {
  Terminal as XTerm,
} from "@xterm/xterm";

import {
  FitAddon,
} from "@xterm/addon-fit";

import "@xterm/xterm/css/xterm.css";


type TerminalProps = {
  labId: string;
  accessToken: string;

  onProcessExit?: (
    exitCode: number,
  ) => void;
};


type TerminalMessage =
  | {
      type: "output";
      data: string;
    }
  | {
      type: "error";
      message: string;
    }
  | {
      type: "run_started";
      path: string;
    }
  | {
      type: "stop_requested";
    }
  | {
      type: "process_exit";
      exit_code: number;
    };


export type TerminalHandle = {
  runFile: (
    path: string,
  ) => boolean;

  stopProcess: () => boolean;
};


const Terminal = forwardRef<
  TerminalHandle,
  TerminalProps
>(
  function Terminal(
    {
      labId,
      accessToken,
      onProcessExit,
    },
    ref,
  ) {
    const terminalElementRef =
      useRef<HTMLDivElement | null>(
        null,
      );

    const websocketRef =
      useRef<WebSocket | null>(
        null,
      );

    /*
     * Keep the latest callback without
     * making the terminal effect depend
     * on the callback.
     */

    const onProcessExitRef =
      useRef<
        ((exitCode: number) => void) | undefined
      >(onProcessExit);


    useEffect(() => {
      onProcessExitRef.current =
        onProcessExit;
    }, [onProcessExit]);


    /*
     * Expose Run / Stop to App.tsx.
     */

    useImperativeHandle(
      ref,
      () => ({
        runFile(path: string) {
          const websocket =
            websocketRef.current;

          if (!websocket) {
            console.warn(
              "Run requested but WebSocket does not exist.",
            );

            return false;
          }

          if (
            websocket.readyState !==
            WebSocket.OPEN
          ) {
            console.warn(
              "Run requested but WebSocket is not open. State:",
              websocket.readyState,
            );

            return false;
          }

          websocket.send(
            JSON.stringify({
              type: "run",
              path,
            }),
          );

          return true;
        },


        stopProcess() {
          const websocket =
            websocketRef.current;

          if (!websocket) {
            console.warn(
              "Stop requested but WebSocket does not exist.",
            );

            return false;
          }

          if (
            websocket.readyState !==
            WebSocket.OPEN
          ) {
            console.warn(
              "Stop requested but WebSocket is not open. State:",
              websocket.readyState,
            );

            return false;
          }

          websocket.send(
            JSON.stringify({
              type: "stop",
            }),
          );

          return true;
        },
      }),
      [],
    );


    /*
     * Create terminal + WebSocket.
     *
     * This effect reconnects when the Lab or authenticated session changes.
     */

    useEffect(() => {
      const element =
        terminalElementRef.current;

      if (!element) {
        return;
      }


      /*
       * Create xterm.
       */

      const terminal =
        new XTerm({
          cursorBlink: true,
          fontSize: 14,
          convertEol: true,
          scrollback: 5000,
        });


      const fitAddon =
        new FitAddon();


      terminal.loadAddon(
        fitAddon,
      );

      terminal.open(
        element,
      );


      requestAnimationFrame(() => {
        fitAddon.fit();
      });


      /*
       * Create WebSocket.
       */

      const websocket =
        new WebSocket(
          `${(import.meta.env.VITE_API_URL as string).replace(/^http/, "ws")}/labs/${labId}/terminal?access_token=${encodeURIComponent(accessToken)}`,
        );


      /*
       * IMPORTANT:
       *
       * This socket becomes the current
       * socket immediately.
       */

      websocketRef.current =
        websocket;


      websocket.onopen = () => {
        terminal.write(
          "\r\nConnected to WPL terminal.\r\n",
        );

        console.log(
          "WPL terminal WebSocket connected.",
        );
      };


      websocket.onmessage = (
        event,
      ) => {
        try {
          const message:
            TerminalMessage =
            JSON.parse(
              event.data,
            );


          /*
           * Normal terminal output.
           */

          if (
            message.type ===
            "output"
          ) {
            terminal.write(
              message.data,
            );

            return;
          }


          /*
           * Backend error.
           */

          if (
            message.type ===
            "error"
          ) {
            terminal.write(
              `\r\nError: ${message.message}\r\n`,
            );

            return;
          }


          /*
           * Run acknowledgement.
           */

          if (
            message.type ===
            "run_started"
          ) {
            return;
          }


          /*
           * Stop acknowledgement.
           */

          if (
            message.type ===
            "stop_requested"
          ) {
            return;
          }


          /*
           * Process actually exited.
           */

          if (
            message.type ===
            "process_exit"
          ) {
            onProcessExitRef.current?.(
              message.exit_code,
            );

            return;
          }

        } catch (error) {
          console.error(
            "Failed to parse terminal message:",
            error,
          );
        }
      };


      websocket.onerror = () => {
        terminal.write(
          "\r\nWebSocket error.\r\n",
        );

        console.error(
          "WPL terminal WebSocket error.",
        );
      };


      websocket.onclose = () => {
        terminal.write(
          "\r\n\r\nTerminal connection closed.\r\n",
        );

        console.log(
          "WPL terminal WebSocket closed.",
        );

        /*
         * IMPORTANT:
         *
         * Only clear the ref if THIS
         * socket is still the current
         * socket.
         *
         * An old socket must never
         * destroy the reference to a
         * newer socket.
         */

        if (
          websocketRef.current ===
          websocket
        ) {
          websocketRef.current =
            null;
        }
      };


      /*
       * Keyboard input.
       */

      const dataDisposable =
        terminal.onData(
          (data) => {
            if (
              websocket.readyState ===
              WebSocket.OPEN
            ) {
              websocket.send(
                JSON.stringify({
                  type: "input",
                  data,
                }),
              );
            }
          },
        );


      /*
       * Resize handling.
       */

      const handleResize = () => {
        fitAddon.fit();
      };


      window.addEventListener(
        "resize",
        handleResize,
      );


      /*
       * Observe terminal container
       * size changes.
       */

      const resizeObserver =
        new ResizeObserver(
          () => {
            fitAddon.fit();
          },
        );


      resizeObserver.observe(
        element,
      );


      /*
       * Cleanup.
       */

      return () => {
        dataDisposable.dispose();

        resizeObserver.disconnect();

        window.removeEventListener(
          "resize",
          handleResize,
        );


        if (
          websocket.readyState ===
            WebSocket.OPEN ||
          websocket.readyState ===
            WebSocket.CONNECTING
        ) {
          websocket.close();
        }


        /*
         * Again, only clear the ref
         * if this is still the active
         * WebSocket.
         */

        if (
          websocketRef.current ===
          websocket
        ) {
          websocketRef.current =
            null;
        }


        terminal.dispose();
      };

    }, [labId]);


    return (
      <div
        ref={
          terminalElementRef
        }
        className="terminal"
      />
    );
  },
);


export default Terminal;