import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { profileApi } from "./api";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: profileApi.me });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: profileApi.updateProfile,
    onSuccess: (data) => {
      queryClient.setQueryData(["me"], data);
    },
  });
}

export function useChangePassword() {
  return useMutation({
    mutationFn: profileApi.changePassword,
  });
}
