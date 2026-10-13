import gallery from "../data/gallery.json";
import { BriefApp } from "./brief-app";

export default function Page() {
  const apiBase = process.env.NEXT_PUBLIC_AGENT_API_URL ?? "";
  return <BriefApp gallery={gallery} apiBase={apiBase} />;
}
