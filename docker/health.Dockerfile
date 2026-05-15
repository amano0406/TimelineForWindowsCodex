FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build

WORKDIR /src
COPY api/TimelineForWindowsCodex.HealthApi/TimelineForWindowsCodex.HealthApi.csproj /src/api/TimelineForWindowsCodex.HealthApi/
RUN dotnet restore /src/api/TimelineForWindowsCodex.HealthApi/TimelineForWindowsCodex.HealthApi.csproj

COPY api/TimelineForWindowsCodex.HealthApi /src/api/TimelineForWindowsCodex.HealthApi
RUN dotnet publish /src/api/TimelineForWindowsCodex.HealthApi/TimelineForWindowsCodex.HealthApi.csproj \
    --configuration Release \
    --no-restore \
    --output /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0

WORKDIR /app
COPY --from=build /app/publish /app

ENV ASPNETCORE_URLS=http://0.0.0.0:8080
ENTRYPOINT ["dotnet", "/app/TimelineForWindowsCodex.HealthApi.dll"]
