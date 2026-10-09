output "lake_bucket" {
  description = "S3 bucket holding the bronze, silver, quarantine and gold prefixes."
  value       = aws_s3_bucket.lake.id
}

output "glue_database" {
  description = "Glue database that holds the lake tables."
  value       = aws_glue_catalog_database.lake.name
}

output "athena_workgroup" {
  description = "Athena workgroup to query the tables with."
  value       = aws_athena_workgroup.conduit.name
}

output "ecr_repository_url" {
  description = "Where to push the pipeline image."
  value       = aws_ecr_repository.conduit.repository_url
}

output "ecs_cluster" {
  description = "Cluster that runs the scheduled task."
  value       = aws_ecs_cluster.conduit.name
}
