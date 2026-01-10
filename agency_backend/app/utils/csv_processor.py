"""Utility for processing CSV files for bulk calls."""
import csv
import io
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)


class CSVProcessor:
    """Process CSV files for bulk call operations."""
    
    @staticmethod
    def parse_csv(file_content: bytes) -> Tuple[List[Dict[str, str]], List[str]]:
        """
        Parse CSV file content and extract phone numbers and names.
        
        Args:
            file_content: Raw bytes of the CSV file
            
        Returns:
            Tuple of (valid_recipients, errors)
            - valid_recipients: List of dicts with 'client_name' and 'number'
            - errors: List of error messages for invalid rows
        """
        try:
            # Decode bytes to string
            content = file_content.decode('utf-8-sig')  # utf-8-sig handles BOM
            csv_file = io.StringIO(content)
            
            # Try to detect dialect
            try:
                dialect = csv.Sniffer().sniff(content[:1024])
                reader = csv.DictReader(csv_file, dialect=dialect)
            except csv.Error:
                csv_file.seek(0)
                reader = csv.DictReader(csv_file)
            
            recipients = []
            errors = []
            
            # Check if required columns exist
            if reader.fieldnames is None:
                errors.append("CSV file is empty or has no headers")
                return recipients, errors
            
            # Normalize header names (case-insensitive, strip whitespace)
            fieldnames_lower = [name.lower().strip() for name in reader.fieldnames]
            
            # Require exact column names: client_name and client_phone
            name_column = None
            if 'client_name' in fieldnames_lower:
                name_column = reader.fieldnames[fieldnames_lower.index('client_name')]
            
            phone_column = None
            if 'client_phone' in fieldnames_lower:
                phone_column = reader.fieldnames[fieldnames_lower.index('client_phone')]
            
            if not name_column or not phone_column:
                errors.append(
                    f"CSV must have exact column names: 'client_name' and 'client_phone'. "
                    f"Found columns: {', '.join(reader.fieldnames)}"
                )
                return recipients, errors
            
            # Process each row
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (1 is header)
                try:
                    name = row.get(name_column, '').strip()
                    phone = row.get(phone_column, '').strip()
                    
                    if not name:
                        errors.append(f"Row {row_num}: Missing name")
                        continue
                    
                    if not phone:
                        errors.append(f"Row {row_num}: Missing phone number")
                        continue
                    
                    # Basic phone validation (will be validated further by the validator)
                    if len(phone) < 10:
                        errors.append(f"Row {row_num}: Phone number too short: {phone}")
                        continue
                    
                    recipients.append({
                        'client_name': name,
                        'number': phone
                    })
                    
                except Exception as e:
                    errors.append(f"Row {row_num}: Error processing row - {str(e)}")
                    continue
            
            if not recipients and not errors:
                errors.append("No valid data found in CSV file")
            
            logger.info(f"[CSV] Parsed {len(recipients)} recipients with {len(errors)} errors")
            return recipients, errors
            
        except UnicodeDecodeError:
            return [], ["CSV file encoding not supported. Please use UTF-8 encoding"]
        except Exception as e:
            logger.error(f"[CSV] Error parsing CSV: {e}")
            return [], [f"Error parsing CSV file: {str(e)}"]
    
    @staticmethod
    def validate_csv_format(filename: str) -> bool:
        """
        Check if filename has valid CSV extension.
        
        Args:
            filename: Name of the file
            
        Returns:
            True if valid CSV file extension
        """
        return filename.lower().endswith(('.csv', '.txt'))
