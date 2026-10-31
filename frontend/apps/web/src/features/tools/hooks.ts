import { useMutation } from "@tanstack/react-query";
import { tryToolQuery, type ToolDef } from "./api";

/** 在线试查（手动触发式 GET）：queryKey 带 def.value 让各接口互不串缓存。 */
export function useTryToolQuery() {
  return useMutation({
    mutationFn: ({ def, values }: { def: ToolDef; values: Record<string, string> }) =>
      tryToolQuery(def, values),
  });
}
