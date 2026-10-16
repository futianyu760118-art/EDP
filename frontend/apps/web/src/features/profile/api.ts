import type { Schemas } from "../../mocks/types";
import { apiClient } from "../auth/api";

/** 个人设置 API（V1.3）：/me + 资料更新 + 改密。 */
export type MeResponse = Schemas["MeResponse"];
export type ProfileUpdateRequest = Schemas["ProfileUpdateRequest"];
export type ChangePasswordResponse = Schemas["ChangePasswordResponse"];

const BASE = "/api/v1/auth";

export const profileApi = {
  me: (): Promise<MeResponse> => apiClient.get<MeResponse>(`${BASE}/me`),

  updateProfile: (body: ProfileUpdateRequest): Promise<MeResponse> =>
    apiClient.put<MeResponse>(`${BASE}/profile`, body),

  changePassword: (body: {
    old_password: string;
    new_password: string;
  }): Promise<ChangePasswordResponse> =>
    apiClient.post<ChangePasswordResponse>(`${BASE}/change-password`, body),
};
