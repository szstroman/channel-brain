import { ImageResponse } from "next/og";

export const runtime = "edge";
export const alt = "Channel Brain";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default async function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#0a0a0a",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div style={{ fontSize: 260, lineHeight: 1, marginBottom: 20 }}>🧠</div>
        <div
          style={{
            fontSize: 100,
            fontWeight: 900,
            color: "#f5f0e8",
            letterSpacing: -2,
            marginBottom: 12,
            fontFamily: "Georgia, serif",
          }}
        >
          Channel Brain
        </div>
        <div
          style={{
            fontSize: 28,
            color: "#5eb8ff",
            letterSpacing: 6,
            textTransform: "uppercase",
            fontFamily: "monospace",
          }}
        >
          Chat with any YouTube archive
        </div>
      </div>
    ),
    {
      ...size,
    },
  );
}
