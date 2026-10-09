locals {
  database_name = "${replace(var.name_prefix, "-", "_")}_311"

  bronze_columns = [
    { name = "unique_key", type = "string" },
    { name = "created_date", type = "string" },
    { name = "closed_date", type = "string" },
    { name = "resolution_action_updated_date", type = "string" },
    { name = "agency", type = "string" },
    { name = "complaint_type", type = "string" },
    { name = "descriptor", type = "string" },
    { name = "status", type = "string" },
    { name = "incident_zip", type = "string" },
    { name = "borough", type = "string" },
    { name = "latitude", type = "string" },
    { name = "longitude", type = "string" },
    { name = "_batch_id", type = "string" },
    { name = "_source", type = "string" },
    { name = "_ingested_at", type = "timestamp" },
  ]

  silver_columns = [
    { name = "unique_key", type = "bigint" },
    { name = "created_at", type = "timestamp" },
    { name = "closed_at", type = "timestamp" },
    { name = "updated_at", type = "timestamp" },
    { name = "agency", type = "string" },
    { name = "complaint_type", type = "string" },
    { name = "descriptor", type = "string" },
    { name = "status", type = "string" },
    { name = "incident_zip", type = "string" },
    { name = "borough", type = "string" },
    { name = "latitude", type = "double" },
    { name = "longitude", type = "double" },
    { name = "response_hours", type = "double" },
    { name = "ingest_date", type = "date" },
  ]

  # Every table carries the same four attributes so they share one object type.
  tables = {
    bronze_311 = {
      location       = "bronze/"
      columns        = local.bronze_columns
      partition_keys = [{ name = "ingest_date", type = "date" }]

      parameters = {
        "projection.enabled"            = "true"
        "projection.ingest_date.type"   = "date"
        "projection.ingest_date.range"  = "2024-01-01,NOW"
        "projection.ingest_date.format" = "yyyy-MM-dd"
        "storage.location.template"     = "s3://${var.lake_bucket_name}/bronze/ingest_date=$${ingest_date}"
      }
    }

    silver_311 = {
      location       = "silver/silver_311/"
      columns        = local.silver_columns
      partition_keys = []
      parameters     = {}
    }

    quarantine_311 = {
      location       = "quarantine/quarantine_311/"
      columns        = concat(local.silver_columns, [{ name = "failed_rules", type = "string" }])
      partition_keys = []
      parameters     = {}
    }

    response_time_by_borough_month = {
      location = "gold/response_time_by_borough_month/"

      columns = [
        { name = "month", type = "date" },
        { name = "borough", type = "string" },
        { name = "closed_tickets", type = "bigint" },
        { name = "median_response_hours", type = "double" },
        { name = "p90_response_hours", type = "double" },
        { name = "mean_response_hours", type = "double" },
      ]
      partition_keys = []
      parameters     = {}
    }

    top_complaints_by_zip = {
      location = "gold/top_complaints_by_zip/"

      columns = [
        { name = "incident_zip", type = "string" },
        { name = "rank", type = "bigint" },
        { name = "complaint_type", type = "string" },
        { name = "tickets", type = "bigint" },
        { name = "share_of_zip", type = "double" },
      ]
      partition_keys = []
      parameters     = {}
    }

    sla_breach_rate = {
      location = "gold/sla_breach_rate/"

      columns = [
        { name = "agency", type = "string" },
        { name = "month", type = "date" },
        { name = "tickets", type = "bigint" },
        { name = "breached_tickets", type = "bigint" },
        { name = "breach_rate", type = "double" },
        { name = "sla_hours", type = "int" },
      ]
      partition_keys = []
      parameters     = {}
    }
  }
}

resource "aws_glue_catalog_database" "lake" {
  name        = local.database_name
  description = "Tables for the conduit NYC 311 pipeline: bronze, silver, quarantine and gold."
}

resource "aws_glue_catalog_table" "lake" {
  for_each = local.tables

  name          = each.key
  database_name = aws_glue_catalog_database.lake.name
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(
    {
      EXTERNAL       = "TRUE"
      classification = "parquet"
    },
    each.value.parameters,
  )

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.lake.id}/${each.value.location}"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    dynamic "columns" {
      for_each = each.value.columns

      content {
        name = columns.value.name
        type = columns.value.type
      }
    }
  }

  dynamic "partition_keys" {
    for_each = each.value.partition_keys

    content {
      name = partition_keys.value.name
      type = partition_keys.value.type
    }
  }
}
