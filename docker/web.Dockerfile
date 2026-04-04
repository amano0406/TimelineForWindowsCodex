FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY web/WindowsCodex2Timeline.Web.csproj web/
RUN dotnet restore web/WindowsCodex2Timeline.Web.csproj

COPY web/ web/
COPY configs/ /src/configs/
RUN dotnet publish web/WindowsCodex2Timeline.Web.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app/publish .
COPY configs/ /app/config/
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "WindowsCodex2Timeline.Web.dll"]

